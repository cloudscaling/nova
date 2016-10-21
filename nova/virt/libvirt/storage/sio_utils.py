# Copyright (c) 2015 - 2016 EMC Corporation.
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

import base64
import binascii

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units
import six

from nova import exception
from nova.i18n import _
from nova import utils
from nova.virt import images
from nova.virt.libvirt import utils as libvirt_utils

try:
    import siolib
except ImportError:
    siolib = None

LOG = logging.getLogger(__name__)
CONF = cfg.CONF

VOLSIZE_MULTIPLE_GB = 8
MAX_VOL_NAME_LENGTH = 31
PROTECTION_DOMAIN_KEY = 'sio:pd_name'
STORAGE_POOL_KEY = 'sio:sp_name'
PROVISIONING_TYPE_KEY = 'sio:provisioning_type'
PROVISIONING_TYPES_MAP = {'thin': 'ThinProvisioned',
                          'thick': 'ThickProvisioned'}

_sdc_guid = None


def verify_volume_size(requested_size):
    """Verify that ScaleIO can have a volume with specified size.

    ScaleIO creates volumes in multiples of 8.
    :param requested_size: Size in bytes
    :return: True if the size fit to ScaleIO, False otherwise
    """
    if (not requested_size or
            requested_size % (units.Gi * VOLSIZE_MULTIPLE_GB)):
        raise exception.NovaException(
            _('Invalid disk size %s GB for the instance. The correct size '
              'must be multiple of 8 GB. Choose another flavor') %
            (requested_size / float(units.Gi)
             if isinstance(requested_size, int) else
             requested_size))


def choose_volume_size(requested_size):
    """Choose ScaleIO volume size to fit requested size.

    ScaleIO creates volumes in multiples of 8.
    :param requested_size: Size in bytes
    :return: The smallest allowed size in bytes of ScaleIO volume.
    """
    return -(-requested_size / (units.Gi * VOLSIZE_MULTIPLE_GB)) * units.Gi


def get_sio_volume_name(instance, disk_name):
    """Generate ScaleIO volume name for instance disk.

    ScaleIO restricts volume names to be unique, less than 32 symbols,
    consist of alphanumeric symbols only.
    Generated volume names start with a prefix, unique for the instance.
    This allows one to find all instance volumes among all ScaleIO volumes.
    :param instane: instance object
    :param disk_name: disk name (i.e. disk, disk.local, etc)
    :return: The generated name
    """
    sio_name = _uuid_to_base64(instance.uuid)
    if disk_name.startswith('disk.'):
        sio_name += disk_name[len('disk.'):]
    elif disk_name != 'disk':
        sio_name += disk_name
    if len(sio_name) > MAX_VOL_NAME_LENGTH:
        raise RuntimeError(_("Disk name '%s' is too long for ScaleIO") %
                           disk_name)
    return sio_name


def get_sio_snapshot_name(volume_name, snapshot_name):
    if snapshot_name == libvirt_utils.RESIZE_SNAPSHOT_NAME:
        return volume_name + '/~'
    sio_name = '%s/%s' % (volume_name, snapshot_name)
    if len(sio_name) > MAX_VOL_NAME_LENGTH:
        raise RuntimeError(_("Snapshot name '%s' is too long for ScaleIO") %
                           snapshot_name)
    return sio_name


def is_sio_volume_rescuer(volume_name):
    return volume_name.endswith('rescue')

def probe_partitions(device_path, run_as_root=False):
    """Method called to trigger OS and inform the OS of partition table changes

    When ScaleIO maps a volume, there is a delay in the time the OS trigger
    probes for partitions. This method will force that trigger so the OS
    will see the device partitions
    :param device_path: Full device path to probe
    :return: Nothing
    """
    try:
        utils.execute('partprobe', device_path, run_as_root=run_as_root)
    except processutils.ProcessExecutionError as exc:
        LOG.debug("Probing the device partitions has failed. (%s)", exc)


def _uuid_to_base64(uuid):
    # This function is copied from Cinder's ScaleIO volume driver
    name = six.text_type(uuid).replace("-", "")
    try:
        name = base64.b16decode(name.upper())
    except (TypeError, binascii.Error):
        pass
    encoded_name = name
    if isinstance(encoded_name, six.text_type):
        encoded_name = encoded_name.encode('utf-8')
    encoded_name = base64.b64encode(encoded_name)
    if six.PY3:
        encoded_name = encoded_name.decode('ascii')
    return encoded_name


def _get_sdc_guid():
    global _sdc_guid
    if not _sdc_guid:
        if CONF.scaleio.default_sdcguid:
            _sdc_guid = CONF.scaleio.default_sdcguid
        else:
            (out, _err) = utils.execute('drv_cfg', '--query_guid',
                                        run_as_root=True)
            LOG.info('Acquire ScaleIO SDC guid %s', out)
            _sdc_guid = out
    return _sdc_guid


class SIODriver(object):
    """Backend image type driver for ScaleIO"""

    def __init__(self):
        """Initialize ScaleIODriver object.

        :return: Nothing
        """
        if siolib is None:
            raise RuntimeError(_('ScaleIO python libraries not found'))

        self.ioctx = siolib.ScaleIO(
            rest_server_ip=CONF.scaleio.rest_server_ip,
            rest_server_port=CONF.scaleio.rest_server_port,
            rest_server_username=CONF.scaleio.rest_server_username,
            rest_server_password=CONF.scaleio.rest_server_password,
            verify_server_certificate=CONF.scaleio.verify_server_certificate,
            server_certificate_path=CONF.scaleio.server_certificate_path)

    def get_pool_info(self):
        """Return the total storage pool info."""

        used_bytes, total_bytes, free_bytes = (
            self.ioctx.storagepool_size(CONF.scaleio.protection_domain_name,
                                        CONF.scaleio.storage_pool_name))
        return {'total': total_bytes,
                'free': free_bytes,
                'used': used_bytes}

    def create_volume(self, name, size, extra_specs):
        """Create a ScaleIO volume.

        :param name: Volume name to use
        :param size: Size of volume to create
        :param extra_specs: A dict of instance flavor extra specs
        :return: Nothing
        """
        pd_name = extra_specs.get(PROTECTION_DOMAIN_KEY,
                                  CONF.scaleio.protection_domain_name
                                  ).encode('utf8')
        sp_name = extra_specs.get(STORAGE_POOL_KEY,
                                  CONF.scaleio.storage_pool_name
                                  ).encode('utf8')
        ptype = extra_specs.get(PROVISIONING_TYPE_KEY,
                                CONF.scaleio.provisioning_type)
        ptype = PROVISIONING_TYPES_MAP.get(ptype, ptype)
        self.ioctx.create_volume(name, pd_name, sp_name, ptype,
                                 size / units.Gi)

    def remove_volume(self, name, ignore_mappings=False):
        """Deletes (removes) a ScaleIO volume.

        Removal of a volume erases all the data on the corresponding volume.

        :param name: String ScaleIO volume name to remove
        :param ignore_mappings: Remove even if the volume is mapped to SDCs
        :return: Nothing
        """
        try:
            self.ioctx.delete_volume(name, unmap_on_delete=ignore_mappings)
        except siolib.VolumeNotFound:
            pass

    def map_volume(self, name):
        """Connect to ScaleIO volume.

        Map ScaleIO volume to local block device

        :param name: String ScaleIO volume name to attach
        :return: Local attached volume path
        """
        vol_id = self.get_volume_id(name)
        try:
            self.ioctx.attach_volume(vol_id, _get_sdc_guid())
        except siolib.VolumeAlreadyMapped:
            pass
        return self.ioctx.get_volumepath(vol_id)

    def unmap_volume(self, name):
        """Disconnect from ScaleIO volume.

        Unmap ScaleIO volume from local block device

        :param name: String ScaleIO volume name to detach
        :return: Nothing
        """
        try:
            self.ioctx.detach_volume(name, _get_sdc_guid())
        except (siolib.VolumeNotMapped, siolib.VolumeNotFound):
            pass

    def check_volume_exists(self, name):
        """Check if ScaleIO volume exists.

        :param name: String ScaleIO volume name to check
        :return: True if the volume exists, False otherwise
        """
        try:
            self.ioctx.get_volumeid(name)
            return True
        except siolib.VolumeNotFound:
            return False

    def get_volume_id(self, name):
        """Return the ScaleIO volume ID

        :param name: String ScaleIO volume name to retrieve id from
        :return: ScaleIO volume id
        """
        return self.ioctx.get_volumeid(name)

    def get_volume_name(self, vol_id):
        """Return the ScaleIO volume name.

        :param vol_id: String ScaleIO volume id to retrieve name from
        :return: ScaleIO volume name
        """
        return self.ioctx.get_volumename(vol_id)

    def get_volume_path(self, name):
        """Return the volume device path location.

        :param name: String ScaleIO volume name to get path information about
        :return: Local attached volume path, None if the volume does not exist
                 or is not connected
        """
        try:
            return self.ioctx.get_volumepath(name)
        except siolib.VolumeNotMapped:
            return None

    def get_volume_size(self, name):
        """Return the size of the ScaleIO volume

        :param name: String ScaleIO volume name to get path information about
        :return: Size of ScaleIO volume
        """
        vol_size = self.ioctx.get_volumesize(name)
        return vol_size * units.Ki

    def import_image(self, source, dest):
        """Import glance image onto actual ScaleIO block device.

        :param source: Glance image source
        :param dest: Target ScaleIO block device
        :return: Nothing
        """
        info = images.qemu_img_info(source)
        images.convert_image(source, dest, info.file_format, 'raw',
                             run_as_root=True)
        # trigger OS probe of partition devices
        probe_partitions(device_path=dest, run_as_root=True)

    def export_image(self, source, dest, out_format):
        """Export ScaleIO volume.

        :param source: Local attached ScaleIO volume path to export from
        :param dest: Target path
        :param out_format: Output format (raw, qcow2, etc)
        :return: Nothing
        """
        images.convert_image(source, dest, 'raw', out_format, run_as_root=True)

    def extend_volume(self, name, new_size):
        """Extend the size of a volume.

        This method is used primarily with openstack resize operation

        :param name: String ScaleIO volume name to extend
        :param new_size: Size of the volume to extend to
        :return: Nothing
        """
        self.ioctx.extend_volume(name, new_size / units.Gi)

    def move_volume(self, name, extra_specs, orig_extra_specs):
        """Move a volume to another protection domain or storage pool.

        :param name: String ScaleIO volume name to extend
        :param extra_specs: A dict of instance flavor extra specs
        :param orig_extra_specs: A dict of original instance flavor extra specs
        :return: Nothing
        """

        if (extra_specs.get(PROTECTION_DOMAIN_KEY) ==
                orig_extra_specs.get(PROTECTION_DOMAIN_KEY) and
                extra_specs.get(STORAGE_POOL_KEY) ==
                orig_extra_specs.get(STORAGE_POOL_KEY)):
            return
        size = self.get_volume_size(name)
        tmp_name = name + '/#'
        self.create_volume(tmp_name, size, extra_specs)
        try:
            new_path = self.map_volume(tmp_name)
            vol_id = self.get_volume_id(name)
            old_path = self.ioctx.get_volumepath(vol_id)
            if old_path:
                mapped = True
            else:
                mapped = False
                self.ioctx.attach_volume(vol_id)
                old_path = self.ioctx.get_volumepath(vol_id)
                if not old_path:
                    raise RuntimeError(
                        _('Failed to attach disk volume %s') % name)
            utils.execute('dd',
                          'if=%s' % old_path,
                          'of=%s' % new_path,
                          'bs=1M',
                          'iflag=direct',
                          run_as_root=True)
            self.remove_volume(name, ignore_mappings=True)
            if not mapped:
                self.unmap_volume(tmp_name)
            new_id = self.get_volume_id(tmp_name)
            self.ioctx.rename_volume(new_id, name)
        except Exception:
            with excutils.save_and_reraise_exception():
                self.remove_volume(tmp_name, ignore_mappings=True)

    def snapshot_volume(self, name, snapshot_name):
        """Snapshot a volume.

        :param name: String ScaleIO volume name to make a snapshot
        :param snapshot_name: String ScaleIO snapshot name to create
        :return: Nothing
        """
        self.ioctx.snapshot_volume(name, snapshot_name)

    def rollback_to_snapshot(self, name, snapshot_name):
        """Rollback a snapshot.

        :param name: String ScaleIO volume name to rollback to a snapshot
        :param snapshot_name: String ScaleIO snapshot name to rollback to
        :return: Nothing
        """
        snap_id = self.get_volume_id(snapshot_name)
        self.remove_volume(name, ignore_mappings=True)
        self.ioctx.rename_volume(snap_id, name)
        self.map_volume(name)

    def map_volumes(self, instance):
        """Map all instance volumes to its compute host.

        :param intance: Instance object
        :return: Nothing
        """
        volumes = self.ioctx.list_volume_names()
        prefix = _uuid_to_base64(instance.uuid)
        volumes = (vol for vol in volumes if vol.startswith(prefix))
        for volume in volumes:
            self.map_volume(volume)

    def cleanup_volumes(self, instance, unmap_only=False):
        """Cleanup all instance volumes.

        :param instance: Instance object
        :param unmap_only: Do not remove, only unmap from the instance host
        :return: Nothing
        """
        volumes = self.ioctx.list_volume_names()
        prefix = _uuid_to_base64(instance.uuid)
        volumes = (vol for vol in volumes if vol.startswith(prefix))
        for volume in volumes:
            if unmap_only:
                self.unmap_volume(volume)
            else:
                self.remove_volume(volume, ignore_mappings=True)

    def cleanup_rescue_volumes(self, instance):
        """Cleanup instance volumes used in rescue mode.

        :param instance: Instance object
        :return: Nothing
        """
        # NOTE(ft): We assume that only root disk is recreated in rescue mode.
        # With this assumption the code becomes more simple and fast.
        rescue_name = _uuid_to_base64(instance.uuid) + 'rescue'
        self.remove_volume(rescue_name, ignore_mappings=True)
