from pathlib import Path
import subprocess
import textwrap

from charmhelpers.core import hookenv, host, templating


LXD_BRIDGE_TMPL = "lxd-bridge.ini.j2"
LXD_BRIDGE_CFG = "/etc/default/lxd-bridge"


class JujuLocalError(Exception):
    """An error in the JujuLocal charm"""


class JujuLocalHelper:
    def __init__(self):
        self.charm_config = hookenv.config()

    def gen_keys(self):
        ssh_key = Path("/home/ubuntu/.ssh/id_rsa")
        if not ssh_key.is_file():
            subprocess.check_call(
                [
                    "sudo",
                    "-u",
                    "ubuntu",
                    "ssh-keygen",
                    "-t",
                    "rsa",
                    "-N",
                    "",
                    "-f",
                    str(ssh_key),
                ]
            )

    def is_xenial(self):
        return host.lsb_release()["DISTRIB_CODENAME"] == "xenial"

    def lxd_init(self):
        if self.is_xenial():
            install_sh = "lxd init --auto --storage-backend dir"
            subprocess.call(install_sh, shell=True)
            self.render_lxd_bridge()
            host.service_restart("lxd-bridge")
        else:
            # bionic or newer
            install_sh = textwrap.dedent(
                """
                lxd init --auto --storage-backend dir
                lxc network delete lxdbr0
                lxc network create lxdbr0 ipv4.address=auto ipv6.address=none"""
            )
            subprocess.call(install_sh, shell=True)

    def setup_juju(self):
        subprocess.call("sudo usermod -aG lxd ubuntu", shell=True)
        if self.is_xenial():
            aa_profile = "lxc.aa_profile"
        else:
            aa_profile = "lxc.apparmor.profile"
        if host.is_container():
            subprocess.call(
                "sudo -u ubuntu lxc profile set default "
                "raw.lxc {}=unconfined".format(aa_profile),
                shell=True,
            )
        subprocess.call(
            textwrap.dedent(
                """
                sudo -u ubuntu bash <<eof
                /snap/bin/juju clouds
                /snap/bin/lxc network set lxdbr0 ipv6.address none
                /snap/bin/juju bootstrap localhost lxd
                eof"""
            ),
            shell=True,
        )

    @staticmethod
    def _render_resource(source, target, context):
        """Render the template."""
        templating.render(
            source=source,
            templates_dir="templates",
            target=target,
            context=context,
        )

    def render_lxd_bridge(self):
        network_prefix = self.get_lxd_network_prefix()
        self._render_resource(
            LXD_BRIDGE_TMPL,
            LXD_BRIDGE_CFG,
            context={"network_prefix": network_prefix},
        )

    @staticmethod
    def get_lxd_network_prefix():
        """Find a free network prefix

        Find a /24 network prefix, that doesn't conflict with another directly
        connected net, by retrieving existing 10/8 nets, finding the largest
        non-conflicting 10.0/16 and return a 10.X.255/24 with that octet
        """
        out = subprocess.check_output("ip route show root 10/8", shell=True)
        connected_nets = [line.split()[0] for line in out.decode("utf-8").splitlines()]
        existing_octets = set([int(n.split(".")[1]) for n in connected_nets])
        all_ff = set(range(1, 255))
        free_octet = max(all_ff - existing_octets, default=None)
        if free_octet is None:
            raise JujuLocalError("No free net found in {}".format(connected_nets))
        return "10.{}.255".format(free_octet)
