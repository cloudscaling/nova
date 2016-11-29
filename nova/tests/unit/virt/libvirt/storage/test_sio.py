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


class FakeException(BaseException):
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
        self.ioctx.delete_volume.return_value = None

        self.driver.remove_volume(self.vol_id)
        self.ioctx.delete_volume.assert_called_with(
            self.vol_id, unmap_on_delete=False)

    def test_remove_volume_by_name(self):
        self.ioctx.delete_volume.return_value = None

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
        self.ioctx.attach_volume.return_value = None
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
        self.ioctx.detach_volume.return_value = None
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
        self.ioctx.get_volumesize.return_value = 2
        result = self.driver.get_volume_size(self.vol_id)
        self.assertEqual(2 * 1024, result)
        self.ioctx.get_volumesize.assert_called_with(self.vol_id)
