################################################################################
#  Licensed to the Apache Software Foundation (ASF) under one
#  or more contributor license agreements.  See the NOTICE file
#  distributed with this work for additional information
#  regarding copyright ownership.  The ASF licenses this file
#  to you under the Apache License, Version 2.0 (the
#  "License"); you may not use this file except in compliance
#  with the License.  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
# limitations under the License.
################################################################################
import argparse
import getpass
import glob
import os
import platform
import re
import signal
import socket
import sys
from collections import namedtuple
from string import Template
from subprocess import Popen, PIPE, check_output

from pyflink.find_flink_home import _find_flink_home, _find_flink_source_root


def on_windows():
    return platform.system() == "Windows"


def find_java_executable():
    java_executable = "java.exe" if on_windows() else "java"
    flink_home = _find_flink_home()
    flink_conf_path = os.path.join(flink_home, "conf", "flink-conf.yaml")
    java_home = None

    # get the realpath of tainted path value to avoid CWE22 problem that constructs a path or URI
    # using the tainted value and might allow an attacker to access, modify, or test the existence
    # of critical or sensitive files.
    real_flink_conf_path = os.path.realpath(flink_conf_path)
    if os.path.isfile(real_flink_conf_path):
        with open(real_flink_conf_path, "r") as f:
            flink_conf_yaml = f.read()
        java_homes = re.findall(r'^[ ]*env\.java\.home[ ]*: ([^#]*).*$', flink_conf_yaml)
        if len(java_homes) > 1:
            java_home = java_homes[len(java_homes) - 1].strip()

    if java_home is None and "JAVA_HOME" in os.environ:
        java_home = os.environ["JAVA_HOME"]

    if java_home is not None:
        java_executable = os.path.join(java_home, "bin", java_executable)

    return java_executable


def construct_log_settings():
    templates = [
        "-Dlog.file=${flink_log_dir}/flink-${flink_ident_string}-python-${hostname}.log",
        "-Dlog4j.configuration=${log4j_properties}",
        "-Dlog4j.configurationFile=${log4j_properties}",
        "-Dlogback.configurationFile=${logback_xml}"
    ]

    flink_home = _find_flink_home()
    flink_conf_dir = os.path.join(flink_home, "conf")
    if "FLINK_LOG_DIR" in os.environ:
        flink_log_dir = os.environ["FLINK_LOG_DIR"]
    else:
        flink_log_dir = os.path.join(flink_home, "log")

    if "LOG4J_PROPERTIES" in os.environ:
        log4j_properties = os.environ["LOG4J_PROPERTIES"]
    else:
        log4j_properties = "%s/log4j-cli.properties" % flink_conf_dir

    if "LOGBACK_XML" in os.environ:
        logback_xml = os.environ["LOGBACK_XML"]
    else:
        logback_xml = "%s/logback.xml" % flink_conf_dir

    if "FLINK_IDENT_STRING" in os.environ:
        flink_ident_string = os.environ["FLINK_IDENT_STRING"]
    else:
        flink_ident_string = getpass.getuser()

    hostname = socket.gethostname()
    log_settings = []
    for template in templates:
        log_settings.append(Template(template).substitute(
            log4j_properties=log4j_properties,
            logback_xml=logback_xml,
            flink_log_dir=flink_log_dir,
            flink_ident_string=flink_ident_string,
            hostname=hostname))
    return log_settings


def construct_classpath():
    flink_home = _find_flink_home()
    # get the realpath of tainted path value to avoid CWE22 problem that constructs a path or URI
    # using the tainted value and might allow an attacker to access, modify, or test the existence
    # of critical or sensitive files.
    real_flink_home = os.path.realpath(flink_home)
    if 'FLINK_LIB_DIR' in os.environ:
        flink_lib_directory = os.path.realpath(os.environ['FLINK_LIB_DIR'])
    else:
        flink_lib_directory = os.path.join(real_flink_home, "lib")
    if 'FLINK_OPT_DIR' in os.environ:
        flink_opt_directory = os.path.realpath(os.environ['FLINK_OPT_DIR'])
    else:
        flink_opt_directory = os.path.join(real_flink_home, "opt")
    if on_windows():
        # The command length is limited on Windows. To avoid the problem we should shorten the
        # command length as much as possible.
        lib_jars = os.path.join(flink_lib_directory, "*")
    else:
        lib_jars = os.pathsep.join(glob.glob(os.path.join(flink_lib_directory, "*.jar")))

    flink_python_jars = glob.glob(os.path.join(flink_opt_directory, "flink-python*.jar"))
    if len(flink_python_jars) < 1:
        print("The flink-python jar is not found in the opt folder of the FLINK_HOME: %s" %
              flink_home)
        return lib_jars
    flink_python_jar = flink_python_jars[0]

    return os.pathsep.join([lib_jars, flink_python_jar])


def download_apache_avro():
    """
    Currently we need to download the Apache Avro manually to avoid test failure caused by the avro
    format sql jar. See https://issues.apache.org/jira/browse/FLINK-17417. If the issue is fixed,
    this method could be removed. Using maven command copy the jars in repository to avoid accessing
    external network.
    """
    flink_source_root = _find_flink_source_root()
    avro_jar_pattern = os.path.join(
        flink_source_root, "flink-formats", "flink-avro", "target", "avro*.jar")
    if len(glob.glob(avro_jar_pattern)) > 0:
        # the avro jar already existed, just return.
        return
    mvn = "mvn.cmd" if on_windows() else "mvn"
    avro_version_output = check_output(
        [mvn, "help:evaluate", "-Dexpression=avro.version"],
        cwd=flink_source_root).decode("utf-8")
    lines = avro_version_output.replace("\r", "").split("\n")
    avro_version = None
    for line in lines:
        if line.strip() != "" and re.match(r'^[0-9]+\.[0-9]+(\.[0-9]+)?$', line.strip()):
            avro_version = line
            break
    if avro_version is None:
        raise Exception("The Apache Avro version is not found in the maven command output:\n %s" %
                        avro_version_output)
    check_output(
        [mvn,
         "org.apache.maven.plugins:maven-dependency-plugin:2.10:copy",
         "-Dartifact=org.apache.avro:avro:%s:jar" % avro_version,
         "-DoutputDirectory=%s/flink-formats/flink-avro/target" % flink_source_root],
        cwd=flink_source_root)


def construct_test_classpath():
    test_jar_patterns = [
        "flink-runtime/target/flink-runtime*tests.jar",
        "flink-streaming-java/target/flink-streaming-java*tests.jar",
        "flink-formats/flink-csv/target/flink-csv*.jar",
        "flink-formats/flink-avro/target/flink-avro*.jar",
        "flink-formats/flink-avro/target/avro*.jar",
        "flink-formats/flink-json/target/flink-json*.jar",
        "flink-python/target/artifacts/testDataStream.jar",
        "flink-python/target/flink-python*-tests.jar",
    ]
    test_jars = []
    flink_source_root = _find_flink_source_root()
    for pattern in test_jar_patterns:
        pattern = pattern.replace("/", os.path.sep)
        test_jars += glob.glob(os.path.join(flink_source_root, pattern))
    return os.path.pathsep.join(test_jars)


def construct_program_args(args):
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--class", required=True)
    parser.add_argument("cluster_type", choices=["local", "remote", "yarn"])
    parse_result, other_args = parser.parse_known_args(args)
    main_class = getattr(parse_result, "class")
    cluster_type = parse_result.cluster_type
    return namedtuple(
        "ProgramArgs", ["main_class", "cluster_type", "other_args"])(
        main_class, cluster_type, other_args)


def prepare_environment_variable(env):
    flink_home = _find_flink_home()
    env = dict(env)
    env["FLINK_CONF_DIR"] = os.path.join(flink_home, "conf")
    env["FLINK_BIN_DIR"] = os.path.join(flink_home, "bin")
    if "FLINK_PLUGINS_DIR" not in env:
        env["FLINK_PLUGINS_DIR"] = os.path.join(flink_home, "plugins")
    if "FLINK_LIB_DIR" not in env:
        env["FLINK_LIB_DIR"] = os.path.join(flink_home, "lib")
    if "FLINK_OPT_DIR" not in env:
        env["FLINK_OPT_DIR"] = os.path.join(flink_home, "opt")
    return env


def launch_gateway_server_process(env, args):
    java_executable = find_java_executable()
    log_settings = construct_log_settings()
    classpath = construct_classpath()
    env = prepare_environment_variable(env)
    if "FLINK_TESTING" in env:
        download_apache_avro()
        classpath = os.pathsep.join([classpath, construct_test_classpath()])
    program_args = construct_program_args(args)
    if program_args.cluster_type == "local":
        command = [java_executable] + log_settings + ["-cp", classpath, program_args.main_class] \
            + program_args.other_args
    else:
        command = [os.path.join(env["FLINK_BIN_DIR"], "flink"), "run"] + program_args.other_args \
            + ["-c", program_args.main_class]
    preexec_fn = None
    if not on_windows():
        def preexec_func():
            # ignore ctrl-c / SIGINT
            signal.signal(signal.SIGINT, signal.SIG_IGN)
        preexec_fn = preexec_func
    return Popen(command, stdin=PIPE, preexec_fn=preexec_fn, env=env)


if __name__ == "__main__":
    launch_gateway_server_process(os.environ, sys.argv[1:])
