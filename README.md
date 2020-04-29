# munin-plugin-arris-cablemodem
Munin plugin(s) that will report the data available from an Arris cablemodem's web interface.
Currently supports certain versions of SB6183 and SB8200.
(If you have another model, see below.)

To install:
1) Be sure the 'speedtest-cli' package is installed for your OS
2) Install the 'bs4' Python package, either with pip3 or your distro's pkg manager.
3) Put the arris.py file in `/usr/local/bin`, make a symlink to it called `wan` in your `/etc/munin/plugins` directory.
4) Add the following block to `/etc/munin/plugin-conf.d/munin-node` so the plugin has enough privileges.
```
[wan]
user munin
group munin
```
5) Restart munin-node (sudo systemctl restart munin-node)
6) Check your graphs in 5 minutes or so (speedtest won't show up until after at least 5 minutes runtime).

My original plan was to create a git patch file that changes the code to fit different model(s) of modem, rather than lots of internal decision points. But ....
After experimenting with other HTML parsers, I found some tricks that better-tolerate the weird differences in the devices' HTML (it's messy stuff), so now the code self-decides based on the model number seen on the main page.

If folks send some files scraped from other models, I'll see about incorporating them, too.
(use 'curl 192.168.100.1 -o status.html' to capture, and also do so for the modem's page that has uptime - they seem to use different URLs by model, so include the name of that page, too.)
