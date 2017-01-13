# Copyright 2012 OpenStack Foundation
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

from tempest.common import compute
from tempest.common.utils import data_utils
from tempest.common import waiters
from tempest import config
from tempest.lib.common.utils import test_utils
from tempest.lib import exceptions
import tempest.test

CONF = config.CONF


class BaseVolumeTest(tempest.test.BaseTestCase):
    """Base test case class for all Cinder API tests."""

    _api_version = 2
    credentials = ['primary']

    @classmethod
    def skip_checks(cls):
        super(BaseVolumeTest, cls).skip_checks()

        if not CONF.service_available.cinder:
            skip_msg = ("%s skipped as Cinder is not available" % cls.__name__)
            raise cls.skipException(skip_msg)
        if cls._api_version == 1:
            if not CONF.volume_feature_enabled.api_v1:
                msg = "Volume API v1 is disabled"
                raise cls.skipException(msg)
        elif cls._api_version == 2:
            if not CONF.volume_feature_enabled.api_v2:
                msg = "Volume API v2 is disabled"
                raise cls.skipException(msg)
        elif cls._api_version == 3:
            if not CONF.volume_feature_enabled.api_v3:
                msg = "Volume API v3 is disabled"
                raise cls.skipException(msg)
        else:
            msg = ("Invalid Cinder API version (%s)" % cls._api_version)
            raise exceptions.InvalidConfiguration(msg)

    @classmethod
    def setup_credentials(cls):
        cls.set_network_resources()
        super(BaseVolumeTest, cls).setup_credentials()

    @classmethod
    def setup_clients(cls):
        super(BaseVolumeTest, cls).setup_clients()
        cls.servers_client = cls.os.servers_client
        cls.compute_networks_client = cls.os.compute_networks_client
        cls.compute_images_client = cls.os.compute_images_client

        if cls._api_version == 1:
            cls.snapshots_client = cls.os.snapshots_client
            cls.volumes_client = cls.os.volumes_client
            cls.backups_client = cls.os.backups_client
            cls.volume_services_client = cls.os.volume_services_client
            cls.volumes_extension_client = cls.os.volumes_extension_client
            cls.availability_zone_client = (
                cls.os.volume_availability_zone_client)
            cls.volume_limits_client = cls.os.volume_limits_client
        else:
            cls.snapshots_client = cls.os.snapshots_v2_client
            cls.volumes_client = cls.os.volumes_v2_client
            cls.backups_client = cls.os.backups_v2_client
            cls.volumes_extension_client = cls.os.volumes_v2_extension_client
            cls.availability_zone_client = (
                cls.os.volume_v2_availability_zone_client)
            cls.volume_limits_client = cls.os.volume_v2_limits_client

    @classmethod
    def resource_setup(cls):
        super(BaseVolumeTest, cls).resource_setup()

        cls.snapshots = []
        cls.volumes = []
        cls.image_ref = CONF.compute.image_ref
        cls.flavor_ref = CONF.compute.flavor_ref
        cls.build_interval = CONF.volume.build_interval
        cls.build_timeout = CONF.volume.build_timeout

        if cls._api_version == 1:
            # Special fields and resp code for cinder v1
            cls.special_fields = {'name_field': 'display_name',
                                  'descrip_field': 'display_description'}
        else:
            # Special fields and resp code for cinder v2
            cls.special_fields = {'name_field': 'name',
                                  'descrip_field': 'description'}

    @classmethod
    def resource_cleanup(cls):
        cls.clear_snapshots()
        cls.clear_volumes()
        super(BaseVolumeTest, cls).resource_cleanup()

    @classmethod
    def create_volume(cls, wait_until='available', **kwargs):
        """Wrapper utility that returns a test volume.

           :param wait_until: wait till volume status.
        """
        if 'size' not in kwargs:
            kwargs['size'] = CONF.volume.volume_size

        if 'imageRef' in kwargs:
            image = cls.compute_images_client.show_image(
                kwargs['imageRef'])['image']
            min_disk = image.get('minDisk')
            kwargs['size'] = max(kwargs['size'], min_disk)

        name_field = cls.special_fields['name_field']
        if name_field not in kwargs:
            name = data_utils.rand_name(cls.__name__ + '-Volume')
            kwargs[name_field] = name

        volume = cls.volumes_client.create_volume(**kwargs)['volume']
        cls.volumes.append(volume)
        waiters.wait_for_volume_status(cls.volumes_client, volume['id'],
                                       wait_until)
        return volume

    @classmethod
    def create_snapshot(cls, volume_id=1, **kwargs):
        """Wrapper utility that returns a test snapshot."""
        name_field = cls.special_fields['name_field']
        if name_field not in kwargs:
            name = data_utils.rand_name(cls.__name__ + '-Snapshot')
            kwargs[name_field] = name

        snapshot = cls.snapshots_client.create_snapshot(
            volume_id=volume_id, **kwargs)['snapshot']
        cls.snapshots.append(snapshot)
        waiters.wait_for_snapshot_status(cls.snapshots_client,
                                         snapshot['id'], 'available')
        return snapshot

    def create_backup(self, volume_id, backup_client=None, **kwargs):
        """Wrapper utility that returns a test backup."""
        if backup_client is None:
            backup_client = self.backups_client

        backup = backup_client.create_backup(
            volume_id=volume_id, **kwargs)['backup']
        self.addCleanup(backup_client.delete_backup, backup['id'])
        waiters.wait_for_backup_status(backup_client, backup['id'],
                                       'available')
        return backup

    # NOTE(afazekas): these create_* and clean_* could be defined
    # only in a single location in the source, and could be more general.

    @staticmethod
    def delete_volume(client, volume_id):
        """Delete volume by the given client"""
        client.delete_volume(volume_id)
        client.wait_for_resource_deletion(volume_id)

    @staticmethod
    def delete_snapshot(client, snapshot_id):
        """Delete snapshot by the given client"""
        client.delete_snapshot(snapshot_id)
        client.wait_for_resource_deletion(snapshot_id)

    def attach_volume(self, server_id, volume_id):
        """Attach a volume to a server"""
        self.servers_client.attach_volume(
            server_id, volumeId=volume_id,
            device='/dev/%s' % CONF.compute.volume_device_name)
        waiters.wait_for_volume_status(self.volumes_client,
                                       volume_id, 'in-use')
        self.addCleanup(waiters.wait_for_volume_status, self.volumes_client,
                        volume_id, 'available')
        self.addCleanup(self.servers_client.detach_volume, server_id,
                        volume_id)

    @classmethod
    def clear_volumes(cls):
        for volume in cls.volumes:
            try:
                cls.volumes_client.delete_volume(volume['id'])
            except Exception:
                pass

        for volume in cls.volumes:
            try:
                cls.volumes_client.wait_for_resource_deletion(volume['id'])
            except Exception:
                pass

    @classmethod
    def clear_snapshots(cls):
        for snapshot in cls.snapshots:
            test_utils.call_and_ignore_notfound_exc(
                cls.snapshots_client.delete_snapshot, snapshot['id'])

        for snapshot in cls.snapshots:
            test_utils.call_and_ignore_notfound_exc(
                cls.snapshots_client.wait_for_resource_deletion,
                snapshot['id'])

    def create_server(self, **kwargs):
        name = kwargs.pop(
            'name',
            data_utils.rand_name(self.__class__.__name__ + '-instance'))

        tenant_network = self.get_tenant_network()
        body, _ = compute.create_test_server(
            self.os,
            tenant_network=tenant_network,
            name=name,
            **kwargs)

        self.addCleanup(test_utils.call_and_ignore_notfound_exc,
                        waiters.wait_for_server_termination,
                        self.servers_client, body['id'])
        self.addCleanup(test_utils.call_and_ignore_notfound_exc,
                        self.servers_client.delete_server, body['id'])
        return body


class BaseVolumeAdminTest(BaseVolumeTest):
    """Base test case class for all Volume Admin API tests."""

    credentials = ['primary', 'admin']

    @classmethod
    def setup_clients(cls):
        super(BaseVolumeAdminTest, cls).setup_clients()

        if cls._api_version == 1:
            cls.admin_volume_qos_client = cls.os_adm.volume_qos_client
            cls.admin_volume_services_client = \
                cls.os_adm.volume_services_client
            cls.admin_volume_types_client = cls.os_adm.volume_types_client
            cls.admin_volume_client = cls.os_adm.volumes_client
            cls.admin_hosts_client = cls.os_adm.volume_hosts_client
            cls.admin_snapshots_client = cls.os_adm.snapshots_client
            cls.admin_backups_client = cls.os_adm.backups_client
            cls.admin_encryption_types_client = \
                cls.os_adm.encryption_types_client
            cls.admin_quotas_client = cls.os_adm.volume_quotas_client
            cls.admin_volume_limits_client = cls.os_adm.volume_limits_client
        elif cls._api_version == 2:
            cls.admin_volume_qos_client = cls.os_adm.volume_qos_v2_client
            cls.admin_volume_services_client = \
                cls.os_adm.volume_services_v2_client
            cls.admin_volume_types_client = cls.os_adm.volume_types_v2_client
            cls.admin_volume_client = cls.os_adm.volumes_v2_client
            cls.admin_hosts_client = cls.os_adm.volume_hosts_v2_client
            cls.admin_snapshot_manage_client = \
                cls.os_adm.snapshot_manage_v2_client
            cls.admin_snapshots_client = cls.os_adm.snapshots_v2_client
            cls.admin_backups_client = cls.os_adm.backups_v2_client
            cls.admin_encryption_types_client = \
                cls.os_adm.encryption_types_v2_client
            cls.admin_quotas_client = cls.os_adm.volume_quotas_v2_client
            cls.admin_volume_limits_client = cls.os_adm.volume_v2_limits_client
            cls.admin_capabilities_client = \
                cls.os_adm.volume_capabilities_v2_client
            cls.admin_scheduler_stats_client = \
                cls.os_adm.volume_scheduler_stats_v2_client

    @classmethod
    def resource_setup(cls):
        super(BaseVolumeAdminTest, cls).resource_setup()

        cls.qos_specs = []
        cls.volume_types = []

    @classmethod
    def resource_cleanup(cls):
        cls.clear_qos_specs()
        super(BaseVolumeAdminTest, cls).resource_cleanup()
        cls.clear_volume_types()

    @classmethod
    def create_test_qos_specs(cls, name=None, consumer=None, **kwargs):
        """create a test Qos-Specs."""
        name = name or data_utils.rand_name(cls.__name__ + '-QoS')
        consumer = consumer or 'front-end'
        qos_specs = cls.admin_volume_qos_client.create_qos(
            name=name, consumer=consumer, **kwargs)['qos_specs']
        cls.qos_specs.append(qos_specs['id'])
        return qos_specs

    @classmethod
    def create_volume_type(cls, name=None, **kwargs):
        """Create a test volume-type"""
        name = name or data_utils.rand_name(cls.__name__ + '-volume-type')
        volume_type = cls.admin_volume_types_client.create_volume_type(
            name=name, **kwargs)['volume_type']
        cls.volume_types.append(volume_type['id'])
        return volume_type

    @classmethod
    def clear_qos_specs(cls):
        for qos_id in cls.qos_specs:
            test_utils.call_and_ignore_notfound_exc(
                cls.admin_volume_qos_client.delete_qos, qos_id)

        for qos_id in cls.qos_specs:
            test_utils.call_and_ignore_notfound_exc(
                cls.admin_volume_qos_client.wait_for_resource_deletion, qos_id)

    @classmethod
    def clear_volume_types(cls):
        for vol_type in cls.volume_types:
            test_utils.call_and_ignore_notfound_exc(
                cls.admin_volume_types_client.delete_volume_type, vol_type)

        for vol_type in cls.volume_types:
            test_utils.call_and_ignore_notfound_exc(
                cls.admin_volume_types_client.wait_for_resource_deletion,
                vol_type)
