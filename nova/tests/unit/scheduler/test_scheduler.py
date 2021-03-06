# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
"""
Tests For Scheduler
"""

import mock
import oslo_messaging as messaging

from nova import context
from nova import objects
from nova.scheduler import caching_scheduler
from nova.scheduler import chance
from nova.scheduler import filter_scheduler
from nova.scheduler import host_manager
from nova.scheduler import manager
from nova import servicegroup
from nova import test
from nova.tests.unit import fake_server_actions
from nova.tests.unit.scheduler import fakes
from nova.tests import uuidsentinel as uuids


class SchedulerManagerInitTestCase(test.NoDBTestCase):
    """Test case for scheduler manager initiation."""
    manager_cls = manager.SchedulerManager

    @mock.patch.object(host_manager.HostManager, '_init_instance_info')
    @mock.patch.object(host_manager.HostManager, '_init_aggregates')
    def test_init_using_default_schedulerdriver(self,
                                                mock_init_agg,
                                                mock_init_inst):
        driver = self.manager_cls().driver
        self.assertIsInstance(driver, filter_scheduler.FilterScheduler)

    @mock.patch.object(host_manager.HostManager, '_init_instance_info')
    @mock.patch.object(host_manager.HostManager, '_init_aggregates')
    def test_init_using_chance_schedulerdriver(self,
                                               mock_init_agg,
                                               mock_init_inst):
        self.flags(driver='chance_scheduler', group='scheduler')
        driver = self.manager_cls().driver
        self.assertIsInstance(driver, chance.ChanceScheduler)

    @mock.patch.object(host_manager.HostManager, '_init_instance_info')
    @mock.patch.object(host_manager.HostManager, '_init_aggregates')
    def test_init_using_caching_schedulerdriver(self,
                                                mock_init_agg,
                                                mock_init_inst):
        self.flags(driver='caching_scheduler', group='scheduler')
        driver = self.manager_cls().driver
        self.assertIsInstance(driver, caching_scheduler.CachingScheduler)

    @mock.patch.object(host_manager.HostManager, '_init_instance_info')
    @mock.patch.object(host_manager.HostManager, '_init_aggregates')
    def test_init_nonexist_schedulerdriver(self,
                                           mock_init_agg,
                                           mock_init_inst):
        self.flags(driver='nonexist_scheduler', group='scheduler')
        # The entry point has to be defined in setup.cfg and nova-scheduler has
        # to be deployed again before using a custom value.
        self.assertRaises(RuntimeError, self.manager_cls)


class SchedulerManagerTestCase(test.NoDBTestCase):
    """Test case for scheduler manager."""

    manager_cls = manager.SchedulerManager
    driver_cls = fakes.FakeScheduler
    driver_plugin_name = 'fake_scheduler'

    @mock.patch.object(host_manager.HostManager, '_init_instance_info')
    @mock.patch.object(host_manager.HostManager, '_init_aggregates')
    def setUp(self, mock_init_agg, mock_init_inst):
        super(SchedulerManagerTestCase, self).setUp()
        self.flags(driver=self.driver_plugin_name, group='scheduler')
        with mock.patch.object(host_manager.HostManager, '_init_aggregates'):
            self.manager = self.manager_cls()
        self.context = context.RequestContext('fake_user', 'fake_project')
        self.topic = 'fake_topic'
        self.fake_args = (1, 2, 3)
        self.fake_kwargs = {'cat': 'meow', 'dog': 'woof'}
        fake_server_actions.stub_out_action_events(self)

    def test_1_correct_init(self):
        # Correct scheduler driver
        manager = self.manager
        self.assertIsInstance(manager.driver, self.driver_cls)

    @mock.patch('nova.scheduler.utils.resources_from_request_spec')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_allocation_candidates')
    def test_select_destination(self, mock_get_ac, mock_rfrs):
        fake_spec = objects.RequestSpec()
        fake_spec.instance_uuid = uuids.instance
        fake_version = "9.42"
        place_res = (fakes.ALLOC_REQS, mock.sentinel.p_sums, fake_version)
        mock_get_ac.return_value = place_res
        expected_alloc_reqs_by_rp_uuid = {
            cn.uuid: [fakes.ALLOC_REQS[x]]
            for x, cn in enumerate(fakes.COMPUTE_NODES)
        }
        with mock.patch.object(self.manager.driver, 'select_destinations'
                ) as select_destinations:
            self.manager.select_destinations(self.context, spec_obj=fake_spec,
                    instance_uuids=[fake_spec.instance_uuid])
            select_destinations.assert_called_once_with(
                self.context, fake_spec,
                [fake_spec.instance_uuid], expected_alloc_reqs_by_rp_uuid,
                mock.sentinel.p_sums, fake_version, False)
            mock_get_ac.assert_called_once_with(
                self.context, mock_rfrs.return_value)

            # Now call select_destinations() with True values for the params
            # introduced in RPC version 4.5
            select_destinations.reset_mock()
            self.manager.select_destinations(None, spec_obj=fake_spec,
                    instance_uuids=[fake_spec.instance_uuid],
                    return_objects=True, return_alternates=True)
            select_destinations.assert_called_once_with(None, fake_spec,
                [fake_spec.instance_uuid], expected_alloc_reqs_by_rp_uuid,
                mock.sentinel.p_sums, fake_version, True)

    @mock.patch('nova.scheduler.utils.resources_from_request_spec')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_allocation_candidates')
    def test_select_destination_return_objects(self, mock_get_ac,
            mock_rfrs):
        fake_spec = objects.RequestSpec()
        fake_spec.instance_uuid = uuids.instance
        fake_version = "9.42"
        place_res = (fakes.ALLOC_REQS, mock.sentinel.p_sums, fake_version)
        mock_get_ac.return_value = place_res
        expected_alloc_reqs_by_rp_uuid = {
            cn.uuid: [fakes.ALLOC_REQS[x]]
            for x, cn in enumerate(fakes.COMPUTE_NODES)
        }
        with mock.patch.object(self.manager.driver, 'select_destinations'
                ) as select_destinations:
            sel_obj = objects.Selection(service_host="fake_host",
                    nodename="fake_node", compute_node_uuid=uuids.compute_node,
                    cell_uuid=uuids.cell, limits=None)
            select_destinations.return_value = [[sel_obj]]
            # Pass True; should get the Selection object back.
            dests = self.manager.select_destinations(None, spec_obj=fake_spec,
                    instance_uuids=[fake_spec.instance_uuid],
                    return_objects=True, return_alternates=True)
            sel_host = dests[0][0]
            self.assertIsInstance(sel_host, objects.Selection)
            # Since both return_objects and return_alternates are True, the
            # driver should have been called with True for return_alternates.
            select_destinations.assert_called_once_with(None, fake_spec,
                    [fake_spec.instance_uuid], expected_alloc_reqs_by_rp_uuid,
                    mock.sentinel.p_sums, fake_version, True)

            # Now pass False for return objects, but keep return_alternates as
            # True. Verify that the manager converted the Selection object back
            # to a dict.
            select_destinations.reset_mock()
            dests = self.manager.select_destinations(None, spec_obj=fake_spec,
                    instance_uuids=[fake_spec.instance_uuid],
                    return_objects=False, return_alternates=True)
            sel_host = dests[0]
            self.assertIsInstance(sel_host, dict)
            # Even though return_alternates was passed as True, since
            # return_objects was False, the driver should have been called with
            # return_alternates as False.
            select_destinations.assert_called_once_with(None, fake_spec,
                    [fake_spec.instance_uuid], expected_alloc_reqs_by_rp_uuid,
                    mock.sentinel.p_sums, fake_version, False)

    @mock.patch('nova.scheduler.utils.resources_from_request_spec')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_allocation_candidates')
    def _test_select_destination(self, get_allocation_candidates_response,
                                 mock_get_ac, mock_rfrs):
        fake_spec = objects.RequestSpec()
        fake_spec.instance_uuid = uuids.instance
        place_res = get_allocation_candidates_response
        mock_get_ac.return_value = place_res
        with mock.patch.object(self.manager.driver, 'select_destinations'
                ) as select_destinations:
            self.assertRaises(messaging.rpc.dispatcher.ExpectedException,
                    self.manager.select_destinations, self.context,
                    spec_obj=fake_spec,
                    instance_uuids=[fake_spec.instance_uuid])
            select_destinations.assert_not_called()
            mock_get_ac.assert_called_once_with(
                self.context, mock_rfrs.return_value)

    def test_select_destination_old_placement(self):
        """Tests that we will raise NoValidhost when the scheduler
        report client's get_allocation_candidates() returns None, None as it
        would if placement service hasn't been upgraded before scheduler.
        """
        place_res = (None, None, None)
        self._test_select_destination(place_res)

    def test_select_destination_placement_connect_fails(self):
        """Tests that we will raise NoValidHost when the scheduler
        report client's get_allocation_candidates() returns None, which it
        would if the connection to Placement failed and the safe_connect
        decorator returns None.
        """
        place_res = None
        self._test_select_destination(place_res)

    def test_select_destination_no_candidates(self):
        """Tests that we will raise NoValidHost when the scheduler
        report client's get_allocation_candidates() returns [], {} which it
        would if placement service hasn't yet had compute nodes populate
        inventory.
        """
        place_res = ([], {}, None)
        self._test_select_destination(place_res)

    @mock.patch('nova.scheduler.request_filter.process_reqspec')
    @mock.patch('nova.scheduler.utils.resources_from_request_spec')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_allocation_candidates')
    def test_select_destination_is_rebuild(self, mock_get_ac, mock_rfrs,
                                           mock_process):
        fake_spec = objects.RequestSpec(
            scheduler_hints={'_nova_check_type': ['rebuild']})
        fake_spec.instance_uuid = uuids.instance
        with mock.patch.object(self.manager.driver, 'select_destinations'
                ) as select_destinations:
            self.manager.select_destinations(self.context, spec_obj=fake_spec,
                    instance_uuids=[fake_spec.instance_uuid])
            select_destinations.assert_called_once_with(
                self.context, fake_spec,
                [fake_spec.instance_uuid], None, None, None, False)
            mock_get_ac.assert_not_called()
            mock_process.assert_not_called()

    @mock.patch('nova.scheduler.utils.resources_from_request_spec')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_allocation_candidates')
    def test_select_destination_with_4_3_client(self, mock_get_ac, mock_rfrs):
        fake_spec = objects.RequestSpec()
        place_res = (fakes.ALLOC_REQS, mock.sentinel.p_sums, "42.0")
        mock_get_ac.return_value = place_res
        expected_alloc_reqs_by_rp_uuid = {
            cn.uuid: [fakes.ALLOC_REQS[x]]
            for x, cn in enumerate(fakes.COMPUTE_NODES)
        }
        with mock.patch.object(self.manager.driver, 'select_destinations'
                ) as select_destinations:
            self.manager.select_destinations(self.context, spec_obj=fake_spec)
            select_destinations.assert_called_once_with(self.context,
                fake_spec, None, expected_alloc_reqs_by_rp_uuid,
                mock.sentinel.p_sums, "42.0", False)
            mock_get_ac.assert_called_once_with(
                self.context, mock_rfrs.return_value)

    # TODO(sbauza): Remove that test once the API v4 is removed
    @mock.patch('nova.scheduler.utils.resources_from_request_spec')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_allocation_candidates')
    @mock.patch.object(objects.RequestSpec, 'from_primitives')
    def test_select_destination_with_old_client(self, from_primitives,
            mock_get_ac, mock_rfrs):
        fake_spec = objects.RequestSpec()
        fake_spec.instance_uuid = uuids.instance
        from_primitives.return_value = fake_spec
        place_res = (fakes.ALLOC_REQS, mock.sentinel.p_sums, "42.0")
        mock_get_ac.return_value = place_res
        expected_alloc_reqs_by_rp_uuid = {
            cn.uuid: [fakes.ALLOC_REQS[x]]
            for x, cn in enumerate(fakes.COMPUTE_NODES)
        }
        with mock.patch.object(self.manager.driver, 'select_destinations'
                ) as select_destinations:
            self.manager.select_destinations(
                self.context, request_spec='fake_spec',
                filter_properties='fake_props',
                instance_uuids=[fake_spec.instance_uuid])
            select_destinations.assert_called_once_with(
                self.context, fake_spec,
                [fake_spec.instance_uuid], expected_alloc_reqs_by_rp_uuid,
                mock.sentinel.p_sums, "42.0", False)
            mock_get_ac.assert_called_once_with(
                self.context, mock_rfrs.return_value)

    def test_update_aggregates(self):
        with mock.patch.object(self.manager.driver.host_manager,
                               'update_aggregates'
                ) as update_aggregates:
            self.manager.update_aggregates(None, aggregates='agg')
            update_aggregates.assert_called_once_with('agg')

    def test_delete_aggregate(self):
        with mock.patch.object(self.manager.driver.host_manager,
                               'delete_aggregate'
                ) as delete_aggregate:
            self.manager.delete_aggregate(None, aggregate='agg')
            delete_aggregate.assert_called_once_with('agg')

    def test_update_instance_info(self):
        with mock.patch.object(self.manager.driver.host_manager,
                               'update_instance_info') as mock_update:
            self.manager.update_instance_info(mock.sentinel.context,
                                              mock.sentinel.host_name,
                                              mock.sentinel.instance_info)
            mock_update.assert_called_once_with(mock.sentinel.context,
                                                mock.sentinel.host_name,
                                                mock.sentinel.instance_info)

    def test_delete_instance_info(self):
        with mock.patch.object(self.manager.driver.host_manager,
                               'delete_instance_info') as mock_delete:
            self.manager.delete_instance_info(mock.sentinel.context,
                                              mock.sentinel.host_name,
                                              mock.sentinel.instance_uuid)
            mock_delete.assert_called_once_with(mock.sentinel.context,
                                                mock.sentinel.host_name,
                                                mock.sentinel.instance_uuid)

    def test_sync_instance_info(self):
        with mock.patch.object(self.manager.driver.host_manager,
                               'sync_instance_info') as mock_sync:
            self.manager.sync_instance_info(mock.sentinel.context,
                                            mock.sentinel.host_name,
                                            mock.sentinel.instance_uuids)
            mock_sync.assert_called_once_with(mock.sentinel.context,
                                              mock.sentinel.host_name,
                                              mock.sentinel.instance_uuids)

    def test_reset(self):
        with mock.patch.object(self.manager.driver.host_manager,
                               'refresh_cells_caches') as mock_refresh:
            self.manager.reset()
            mock_refresh.assert_called_once_with()

    @mock.patch('nova.objects.host_mapping.discover_hosts')
    def test_discover_hosts(self, mock_discover):
        cm1 = objects.CellMapping(name='cell1')
        cm2 = objects.CellMapping(name='cell2')
        mock_discover.return_value = [objects.HostMapping(host='a',
                                                          cell_mapping=cm1),
                                      objects.HostMapping(host='b',
                                                          cell_mapping=cm2)]
        self.manager._discover_hosts_in_cells(mock.sentinel.context)


class SchedulerTestCase(test.NoDBTestCase):
    """Test case for base scheduler driver class."""

    # So we can subclass this test and re-use tests if we need.
    driver_cls = fakes.FakeScheduler

    @mock.patch.object(host_manager.HostManager, '_init_instance_info')
    @mock.patch.object(host_manager.HostManager, '_init_aggregates')
    def setUp(self, mock_init_agg, mock_init_inst):
        super(SchedulerTestCase, self).setUp()
        self.driver = self.driver_cls()
        self.context = context.RequestContext('fake_user', 'fake_project')
        self.topic = 'fake_topic'
        self.servicegroup_api = servicegroup.API()

    @mock.patch('nova.objects.ServiceList.get_by_topic')
    @mock.patch('nova.servicegroup.API.service_is_up')
    def test_hosts_up(self, mock_service_is_up, mock_get_by_topic):
        service1 = objects.Service(host='host1')
        service2 = objects.Service(host='host2')
        services = objects.ServiceList(objects=[service1, service2])

        mock_get_by_topic.return_value = services
        mock_service_is_up.side_effect = [False, True]

        result = self.driver.hosts_up(self.context, self.topic)
        self.assertEqual(result, ['host2'])

        mock_get_by_topic.assert_called_once_with(self.context, self.topic)
        calls = [mock.call(service1), mock.call(service2)]
        self.assertEqual(calls, mock_service_is_up.call_args_list)
