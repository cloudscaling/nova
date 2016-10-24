# Copyright (c) 2016 EMC Corporation.
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

from oslo_config import cfg

sio_group = cfg.OptGroup(
    name='scaleio', title='ScaleIO ephemeral backend configuration values')

sio_opts = [
    # All deprecated things are added to keep backward compatibility with
    # deployments based on
    # https://github.com/codedellemc/nova-scaleio-ephemeral,
    # which deployments might be deployed via
    # Fuel (EMC - ScaleIO Fuel Plugin,
    # https://github.com/openstack/fuel-plugin-scaleio),
    # JuJu (JuJu Charms for ScaleIO,
    # https://github.com/codedellemc/juju-scaleio),
    # Puppet (ScaleIO for OpenStack plugin,
    # https://forge.puppet.com/cloudscaling/scaleio_openstack).
    # These things will be removed after the first Nova release with ScaleIO
    # ephemeral support.
    cfg.StrOpt('rest_server_ip',
               help='The ScaleIO gateway ip address.'),
    cfg.IntOpt('rest_server_port',
               default=443,
               help='The ScaleIO gateway port.'),
    cfg.StrOpt('rest_server_username',
               help='The ScaleIO gateway username.'),
    cfg.StrOpt('rest_server_password',
               help='The ScaleIO gateway password.'),
    cfg.BoolOpt('verify_server_certificate',
                default=False,
                help='Verify server certificate.'),
    cfg.StrOpt('server_certificate_path',
               help='Server certificate path.'),
    cfg.StrOpt('default_sdcguid',
               help='The ScaleIO default SDC guid to use (test use only)'),
    cfg.StrOpt('default_protection_domain_name',
               deprecated_name='protection_domain_name',
               help='The ScaleIO default protection domain'),
    cfg.StrOpt('default_storage_pool_name',
               deprecated_name='storage_pool_name',
               help='The ScaleIO default storage pool'),
    cfg.StrOpt('default_provisioning_type',
               deprecated_name='provisioning_type',
               default='thick',
               choices=('thick', 'thin',
                        # These choices are DEPRECATED.
                        'ThickProvisioned', 'ThinProvisioned'),
               help='Default ScaleIO volume provisioning type.'),
]

ALL_OPTS = sio_opts


def register_opts(conf):
    conf.register_group(sio_group)
    conf.register_opts(ALL_OPTS, group=sio_group)


def list_opts():
    return {sio_group: ALL_OPTS}
