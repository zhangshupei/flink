/*
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package org.apache.flink.table.planner.plan.nodes.physical.stream

import org.apache.flink.table.catalog.{CatalogTable, ObjectIdentifier}
import org.apache.flink.table.connector.sink.DynamicTableSink
import org.apache.flink.table.planner.calcite.FlinkTypeFactory
import org.apache.flink.table.planner.plan.nodes.calcite.Sink
import org.apache.flink.table.planner.plan.nodes.exec.stream.StreamExecSink
import org.apache.flink.table.planner.plan.nodes.exec.{InputProperty, ExecNode}
import org.apache.flink.table.planner.plan.utils.ChangelogPlanUtils

import org.apache.calcite.plan.{RelOptCluster, RelTraitSet}
import org.apache.calcite.rel.RelNode

import java.util

/**
 * Stream physical RelNode to to write data into an external sink defined by a
 * [[DynamicTableSink]].
 */
class StreamPhysicalSink(
    cluster: RelOptCluster,
    traitSet: RelTraitSet,
    inputRel: RelNode,
    tableIdentifier: ObjectIdentifier,
    catalogTable: CatalogTable,
    tableSink: DynamicTableSink)
  extends Sink(cluster, traitSet, inputRel, tableIdentifier, catalogTable, tableSink)
  with StreamPhysicalRel {

  override def requireWatermark: Boolean = false

  override def copy(traitSet: RelTraitSet, inputs: util.List[RelNode]): RelNode = {
    new StreamPhysicalSink(
      cluster, traitSet, inputs.get(0), tableIdentifier, catalogTable, tableSink)
  }

  override def translateToExecNode(): ExecNode[_] = {
    val inputChangelogMode = ChangelogPlanUtils.getChangelogMode(
      getInput.asInstanceOf[StreamPhysicalRel]).get
    new StreamExecSink(
      tableIdentifier.toList,
      catalogTable.getSchema,
      tableSink,
      inputChangelogMode,
      InputProperty.DEFAULT,
      FlinkTypeFactory.toLogicalRowType(getRowType),
      getRelDetailedDescription
    )
  }
}