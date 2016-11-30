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

import mock
from oslo_config import cfg

from nova import test
from nova.virt.libvirt.storage import sio_utils

CONF = cfg.CONF


class FakeException(Exception):
    pass


class SioTestCase(test.NoDBTestCase):

    @mock.patch.object(sio_utils, 'siolib')
    def setUp(self, mock_siolib):
        super(SioTestCase, self).setUp()

        self.vol_name = u'volume-00000001'
        self.vol_size_Gb = 3
        self.vol_size = self.vol_size_Gb * (1024 ** 3)
        self.vol_id = '1x2x3x4x5x'
        self.sdc_uuid = '00-00-00'

        CONF.set_override('default_protection_domain_name', 'fpd', 'scaleio')
        CONF.set_override('default_storage_pool_name', 'fsp', 'scaleio')
        CONF.set_override('default_sdcguid', self.sdc_uuid, 'scaleio')

        self.mock_siolib = mock_siolib
        self.driver = sio_utils.SIODriver()
        self.ioctx = self.driver.ioctx

    def test_get_pool_info(self):
        self.ioctx.storagepool_size.return_value = (99, 211, 112)
        data = self.driver.get_pool_info()
        self.assertEqual(99, data['used'])
        self.assertEqual(211, data['total'])
        self.assertEqual(112, data['free'])
        self.ioctx.storagepool_size.assert_called_with('fpd', 'fsp')

    def test_create_volume_with_defaults(self):
        self.ioctx.create_volume.return_value = (self.vol_id, 'fake_name')

        self.driver.create_volume(self.vol_name, self.vol_size, {})
        self.ioctx.create_volume.assert_called_with(
            self.vol_name, 'fpd', 'fsp', 'ThickProvisioned', self.vol_size_Gb)

    def test_create_volume_with_specs(self):
        self.ioctx.create_volume.return_value = (self.vol_id, 'fake_name')

        specs = {
            'disk:domain': 'fd_1x1',
            'disk:pool': 'fp_1x1',
            'disk:provisioning_type': 'thick',
        }
        self.driver.create_volume(self.vol_name, self.vol_size, specs)
        self.ioctx.create_volume.assert_called_with(
            self.vol_name, 'fd_1x1', 'fp_1x1', 'ThickProvisioned',
            self.vol_size_Gb)

    def test_create_volume_with_legacy_specs(self):
        self.ioctx.create_volume.return_value = (self.vol_id, 'fake_name')

        specs = {
            'sio:pd_name': 'lfd_1x1',
            'sio:sp_name': 'lfp_1x1',
            'sio:provisioning_type': 'thin',
        }
        self.driver.create_volume(self.vol_name, self.vol_size, specs)
        self.ioctx.create_volume.assert_called_with(
            self.vol_name, 'lfd_1x1', 'lfp_1x1', 'ThinProvisioned',
            self.vol_size_Gb)

    def test_remove_volume(self):
        self.driver.remove_volume(self.vol_id)
        self.ioctx.delete_volume.assert_called_with(
            self.vol_id, unmap_on_delete=False)

    def test_remove_volume_by_name(self):
        self.driver.remove_volume(self.vol_name, ignore_mappings=True)
        self.ioctx.delete_volume.assert_called_with(
            self.vol_name, unmap_on_delete=True)

    @mock.patch.object(sio_utils, 'siolib')
    def test_remove_volume_with_error(self, mock_siolib):
        self.ioctx.delete_volume.side_effect = FakeException
        self.assertRaises(FakeException, self.driver.remove_volume,
                          self.vol_id)

        mock_siolib.VolumeNotFound = FakeException
        self.ioctx.delete_volume.side_effect = mock_siolib.VolumeNotFound
        self.driver.remove_volume(self.vol_id)
        self.ioctx.delete_volume.assert_called_with(
            self.vol_id, unmap_on_delete=False)

    def test_map_volume(self):
        self.ioctx.get_volumepath.return_value = '/a/b/c'

        self.driver.map_volume(self.vol_id, with_no_wait=True)

        self.ioctx.attach_volume.assert_called_with(
            self.vol_id, self.sdc_uuid)
        self.ioctx.get_volumepath.assert_called_with(
            self.vol_id, with_no_wait=True)

    @mock.patch.object(sio_utils, 'siolib')
    def test_map_volume_with_error(self, mock_siolib):
        self.ioctx.get_volumepath.return_value = '/a/b/c'

        self.ioctx.attach_volume.side_effect = FakeException
        self.assertRaises(FakeException, self.driver.map_volume, self.vol_id)

        mock_siolib.VolumeAlreadyMapped = FakeException
        self.ioctx.attach_volume.side_effect = mock_siolib.VolumeAlreadyMapped
        self.driver.map_volume(self.vol_id)
        self.ioctx.attach_volume.assert_called_with(
            self.vol_id, self.sdc_uuid)
        self.ioctx.get_volumepath.assert_called_with(
            self.vol_id, with_no_wait=False)

    def test_unmap_volume(self):
        self.driver.unmap_volume(self.vol_id)
        self.ioctx.detach_volume.assert_called_with(
            self.vol_id, self.sdc_uuid)

    @mock.patch.object(sio_utils, 'siolib')
    def test_unmap_volume_with_error(self, mock_siolib):
        self.ioctx.detach_volume.side_effect = FakeException
        self.assertRaises(FakeException, self.driver.unmap_volume, self.vol_id)

        mock_siolib.VolumeNotMapped = FakeException
        self.ioctx.detach_volume.side_effect = mock_siolib.VolumeNotMapped
        self.driver.unmap_volume(self.vol_id)
        self.ioctx.detach_volume.assert_called_with(
            self.vol_id, self.sdc_uuid)

        mock_siolib.VolumeNotFound = FakeException
        self.ioctx.detach_volume.side_effect = mock_siolib.VolumeNotFound
        self.driver.unmap_volume(self.vol_id)
        self.ioctx.detach_volume.assert_called_with(
            self.vol_id, self.sdc_uuid)

    def test_get_volume_id(self):
        self.ioctx.get_volumeid.return_value = self.vol_id
        result = self.driver.get_volume_id(self.vol_name)
        self.assertEqual(self.vol_id, result)
        self.ioctx.get_volumeid.assert_called_with(self.vol_name)

    @mock.patch.object(sio_utils, 'siolib')
    def test_get_volume_id_with_error(self, mock_siolib):
        mock_siolib.VolumeNotFound = FakeException
        self.ioctx.get_volumeid.side_effect = mock_siolib.VolumeNotFound
        self.assertRaises(mock_siolib.VolumeNotFound,
                          self.driver.get_volume_id, self.vol_name)
        result = self.driver.get_volume_id(self.vol_name,
                                           none_if_not_found=True)
        self.assertIsNone(result)
        self.ioctx.get_volumeid.assert_called_with(self.vol_name)

        self.ioctx.get_volumeid.side_effect = FakeException
        self.assertRaises(FakeException, self.driver.get_volume_id,
                          self.vol_name)

    @mock.patch.object(sio_utils, 'siolib')
    def test_check_volume_exists(self, mock_siolib):
        self.ioctx.get_volumeid.return_value = self.vol_id
        result = self.driver.get_volume_id(self.vol_name)
        self.assertTrue(result)
        self.ioctx.get_volumeid.assert_called_with(self.vol_name)

        mock_siolib.VolumeNotFound = FakeException
        self.ioctx.get_volumeid.side_effect = mock_siolib.VolumeNotFound
        result = self.driver.get_volume_id(self.vol_name,
                                           none_if_not_found=True)
        self.assertFalse(result)
        self.ioctx.get_volumeid.assert_called_with(self.vol_name)

    def test_get_volume_name(self):
        self.ioctx.get_volumename.return_value = self.vol_id
        result = self.driver.get_volume_name(self.vol_name)
        self.assertEqual(self.vol_id, result)
        self.ioctx.get_volumename.assert_called_with(self.vol_name)

    @mock.patch.object(sio_utils, 'siolib')
    def test_get_volume_path(self, mock_siolib):
        self.ioctx.get_volumepath.return_value = '/a/b'
        result = self.driver.get_volume_path(self.vol_id)
        self.assertEqual('/a/b', result)
        self.ioctx.get_volumepath.assert_called_with(self.vol_id)

        mock_siolib.VolumeNotMapped = FakeException
        self.ioctx.get_volumepath.side_effect = mock_siolib.VolumeNotMapped
        result = self.driver.get_volume_path(self.vol_id)
        self.assertIsNone(result)
        self.ioctx.get_volumepath.assert_called_with(self.vol_id)

    def test_get_volume_size(self):
        self.ioctx.get_volumesize.return_value = self.vol_size / 1024
        result = self.driver.get_volume_size(self.vol_id)
        self.assertEqual(self.vol_size, result)
        self.ioctx.get_volumesize.assert_called_with(self.vol_id)

    @mock.patch.object(sio_utils, 'images')
    def test_import_image(self, mock_images):
        img_info = mock.Mock()
        setattr(img_info, 'file_format', 'fake')
        mock_images.qemu_img_info.return_value = img_info

        self.driver.import_image('a', 'b')
        mock_images.convert_image.assert_called_with('a', 'b', 'fake', 'raw',
                                                     run_as_root=True)

    @mock.patch.object(sio_utils, 'images')
    def test_export_image(self, mock_images):
        self.driver.export_image('b', 'a', 'c')
        mock_images.convert_image.assert_called_with('b', 'a', 'raw', 'c',
                                                     run_as_root=True)

    def test_extend_volume_without_path(self):
        self.ioctx.get_volumepath.return_value = None
        self.driver.extend_volume(self.vol_id, self.vol_size)
        self.ioctx.extend_volume.assert_called_with(self.vol_id,
                                                    self.vol_size_Gb)
        self.ioctx.get_volumepath.assert_called_with(self.vol_id,
                                                     with_no_wait=True)

    @mock.patch.object(sio_utils, 'utils')
    def test_extend_volume_with_path(self, mock_utils):
        self.ioctx.get_volumepath.return_value = '/a/b'
        mock_utils.execute.return_value = (self.vol_size, None)

        self.driver.extend_volume(self.vol_id, self.vol_size)

        self.ioctx.extend_volume.assert_called_with(self.vol_id,
                                                    self.vol_size_Gb)
        self.ioctx.get_volumepath.assert_called_with(self.vol_id,
                                                     with_no_wait=True)
        mock_utils.execute.assert_called_with('blockdev', '--getsize64',
                                              '/a/b', run_as_root=True)

        # with resize error
        mock_utils.execute.return_value = (2 * (self.vol_size + 1), None)
        self.driver.extend_volume(self.vol_id, self.vol_size)
        mock_utils.execute.assert_called_with('blockdev', '--getsize64',
                                              '/a/b', run_as_root=True)

    def test_move_volume_not_moved(self):
        specs = {'disk:domain': 'a', 'disk:pool': 'b'}
        self.driver.move_volume(self.vol_id, self.vol_name, specs, specs)

    @mock.patch.object(sio_utils, 'utils')
    def test_move_volume(self, mock_utils):
        orig_specs = {'disk:domain': 'aa', 'disk:pool': 'bb'}

        self.ioctx.get_volumesize.return_value = self.vol_size / 1024
        self.ioctx.create_volume.return_value = ('new_id', 'fake_name')
        self.ioctx.get_volumepath.side_effect = (
            lambda x: '/a/b/c' if x == self.vol_id else '/c/b/a')
        mock_utils.execute.return_value = (self.vol_size, None)

        self.driver.move_volume(self.vol_id, self.vol_name, {}, orig_specs)

        self.ioctx.get_volumesize.assert_called_with(self.vol_id)
        self.ioctx.create_volume.assert_called_with(
            self.vol_name + '/#', 'fpd', 'fsp', 'ThickProvisioned',
            self.vol_size_Gb)
        self.ioctx.attach_volume.assert_has_calls(
            [mock.call('new_id', self.sdc_uuid),
             mock.call(self.vol_id, self.sdc_uuid)])
        self.ioctx.get_volumepath.assert_has_calls(
            [mock.call('new_id'), mock.call(self.vol_id)])
        mock_utils.execute.assert_called_with(
            'dd', 'if=/a/b/c', 'of=/c/b/a', 'bs=1M', 'iflag=direct',
            run_as_root=True)
        self.ioctx.delete_volume.assert_called_with(
            self.vol_id, unmap_on_delete=True)
        self.ioctx.detach_volume.assert_called_with(
            'new_id', self.sdc_uuid)
        self.ioctx.rename_volume.assert_called_with(
            'new_id', self.vol_name)

    def test_move_volume_error(self):
        orig_specs = {'disk:domain': 'aa', 'disk:pool': 'bb'}

        self.ioctx.get_volumesize.return_value = self.vol_size / 1024
        self.ioctx.create_volume.return_value = ('new_id', 'fake_name')
        self.ioctx.attach_volume.side_effect = FakeException

        self.assertRaises(FakeException, self.driver.move_volume,
                          self.vol_id, self.vol_name, {}, orig_specs)

        self.ioctx.get_volumesize.assert_called_with(self.vol_id)
        self.ioctx.create_volume.assert_called_with(
            self.vol_name + '/#', 'fpd', 'fsp', 'ThickProvisioned',
            self.vol_size_Gb)
        self.ioctx.delete_volume.assert_called_with(
            'new_id', unmap_on_delete=True)

    def test_snapshot_volume(self):
        self.driver.snapshot_volume(self.vol_id, 'snap_name')
        self.ioctx.snapshot_volume.assert_called_with(self.vol_id, 'snap_name')

    def test_rollback_to_snapshot(self):
        self.ioctx.get_volumeid.return_value = 'snap_id'

        self.driver.rollback_to_snapshot(
            self.vol_id, self.vol_name, 'snap_name')

        self.ioctx.get_volumeid.assert_called_with('snap_name')
        self.ioctx.delete_volume.assert_called_with(
            self.vol_id, unmap_on_delete=True)
        self.ioctx.rename_volume.assert_called_with(
            'snap_id', self.vol_name)
        self.ioctx.attach_volume.assert_called_with(
            'snap_id', self.sdc_uuid)

    def test_map_volumes(self):
        uuid = 'b0d0b498-1fe2-479e-995c-80ace2f339a7'
        self.ioctx.list_volume_infos.return_value = [
            {'name': 'sNC0mB/iR56ZXICs4vM5pw==#1', 'id': '0-1'},
            {'name': 'sNC0mB/iR56ZXICs4vM5pw==#2', 'id': '0-2'}]

        instance = mock.Mock()
        setattr(instance, 'uuid', uuid)
        self.driver.map_volumes(instance)

        self.ioctx.list_volume_infos.assert_called_with()
        self.ioctx.attach_volume.assert_has_calls(
            [mock.call('0-1', '00-00-00'), mock.call('0-2', '00-00-00')])
        self.ioctx.get_volumepath.assert_has_calls(
            [mock.call('0-1', with_no_wait=True),
             mock.call('0-2', with_no_wait=True)])

    def test_cleanup_volumes(self):
        uuid = 'b0d0b498-1fe2-479e-995c-80ace2f339a7'
        self.ioctx.list_volume_infos.return_value = [
            {'name': 'sNC0mB/iR56ZXICs4vM5pw==#1', 'id': '0-1'},
            {'name': 'sNC0mB/iR56ZXICs4vM5pw==#2', 'id': '0-2'}]

        instance = mock.Mock()
        setattr(instance, 'uuid', uuid)
        self.driver.cleanup_volumes(instance)

        self.ioctx.list_volume_infos.assert_called_with()
        self.ioctx.delete_volume.assert_has_calls(
            [mock.call('0-1', unmap_on_delete=True),
             mock.call('0-2', unmap_on_delete=True)])

    def test_cleanup_volumes_unmap_only(self):
        uuid = 'b0d0b498-1fe2-479e-995c-80ace2f339a7'
        self.ioctx.list_volume_infos.return_value = [
            {'name': 'sNC0mB/iR56ZXICs4vM5pw==#1', 'id': '0-1'},
            {'name': 'sNC0mB/iR56ZXICs4vM5pw==#2', 'id': '0-2'}]

        instance = mock.Mock()
        setattr(instance, 'uuid', uuid)
        self.driver.cleanup_volumes(instance, unmap_only=True)

        self.ioctx.list_volume_infos.assert_called_with()
        self.ioctx.detach_volume.assert_has_calls(
            [mock.call('0-1', '00-00-00'), mock.call('0-2', '00-00-00')])

    def test_cleanup_rescue_volumes(self):
        uuid = 'b0d0b498-1fe2-479e-995c-80ace2f339a7'

        instance = mock.Mock()
        setattr(instance, 'uuid', uuid)
        self.driver.cleanup_rescue_volumes(instance)

        self.ioctx.delete_volume.assert_called_with(
            'sNC0mB/iR56ZXICs4vM5pw==rescue', unmap_on_delete=True)
