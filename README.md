# os-arpwatch

An OPNsense plugin that watches for new MAC addresses on your network and
notifies you by **email (SMTP)**, **Telegram** and/or **Pushbullet**. It fills
the role the ARPWatch package has on pfSense.

## How it works

A small Python daemon (`arpwatchd`) inspects the firewall's ARP table, and
optionally the IPv6 neighbour table, every few seconds and records each MAC
address in a SQLite database (`/var/db/arpwatch/arpwatch.db`). It needs no
packages beyond what OPNsense already ships.

| Event | Default | Meaning |
|---|---|---|
| New device | on | A MAC address that was never seen before |
| IP address changed MAC | on | An address is now answered by a different MAC (spoofing, or a reused DHCP lease). At most once per hour per address |
| Known device, new IP | off | A known MAC uses an address it did not use before |

Events found in the same scan are combined into one message. Failed deliveries
are retried up to five times with increasing delays. On the very first run the
devices already present are learned without notifications.

Because it reads the firewall's own neighbour tables, a device is detected once
it exchanges traffic with the firewall (DHCP, DNS, gateway). A device that only
talks to other hosts on the same switch is not seen.

## Installation

### From a release package

Download the package from the
[releases page](https://github.com/wrcrooks/ARPWatch/releases) and install it
on the firewall as root (replace the version with the one you want):

```sh
fetch https://github.com/wrcrooks/ARPWatch/releases/download/v1.0/os-arpwatch-1.0.pkg
pkg add os-arpwatch-1.0.pkg
```

The package contains only scripts, so the same file installs on every
architecture. Remove it again with `pkg delete os-arpwatch`. Since it does not
come from the OPNsense repository, updates are installed the same way, by hand.

### Quick install from a checkout

Copy this repository to the firewall and run, as root:

```sh
sh install.sh          # install or update
sh install.sh remove   # uninstall
```

### Building the package yourself

Build it inside the OPNsense plugins tree:

```sh
opnsense-code plugins
cp -R /path/to/this/repo /usr/plugins/net-mgmt/arpwatch
cd /usr/plugins/net-mgmt/arpwatch
make package PLUGIN_DEVEL=   # result in work/pkg/os-arpwatch-*.pkg
pkg add work/pkg/os-arpwatch-*.pkg
```

## Releasing

The `Package` workflow builds the package in a FreeBSD VM on GitHub Actions.
To publish a release, set `PLUGIN_VERSION` in the `Makefile`, add the changes
to `pkg-descr`, commit, then push a matching tag:

```sh
git tag v1.0
git push origin v1.0
```

The workflow refuses a tag that does not match `PLUGIN_VERSION`. It can also be
started by hand from the Actions tab, which builds the package and keeps it as
a workflow artifact without publishing a release.

## Configuration

Go to **Services > ARPWatch**.

* **General**: enable the service, pick the interfaces (empty means all, you
  will normally want to leave WAN out), the scan interval and the events to
  report. MAC addresses or prefixes can be excluded from notifications.
* **Notifications**: configure one or more delivery methods.
  * *SMTP*: server, port, STARTTLS / SSL / none, optional credentials, sender
    and recipients.
  * *Telegram*: create a bot with [@BotFather](https://t.me/BotFather), send it
    a message, then enter the bot token and your chat id.
  * *Pushbullet*: an access token from your account settings, optionally a
    channel tag.
* **Devices**: every device seen so far. Forgetting a device makes it count as
  new the next time it shows up.

**Save and send test notification** stores the settings and sends a message
through every enabled method, reporting the result of each.

Activity is logged under **Services > ARPWatch > Log File**.

## Notes

* Credentials are stored in `config.xml` like any other OPNsense setting, and
  in `/usr/local/etc/arpwatchd.conf` (mode 0600).
* Phones and laptops using randomised ("private") MAC addresses appear as a new
  device per network, and again whenever they rotate the address. They are
  labelled as such in the notification.
