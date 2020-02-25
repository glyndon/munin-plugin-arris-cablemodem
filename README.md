# munin-plugin-arris-cablemodem
Munin plugin(s) that will report the data available from an Arris cablemodem's web interface.
Currently supports certain versions of SB6183 and SB8200.
(If you have another model, see below.)

To install:
1) Be sure the speedtest-cli package is installed for your OS
2) Use pip3 to install the 'bs4' Python package, and 'html5lib' either with pip3 or your distro's pkg manager.
3) Put the arris.py file in /usr/local/bin, make a symlink to it called 'wan' in your /etc/munin/plugins.
4) Restart munin-node
5) check your graphs in 5 minutes or so.

My plan had been to create a git patch file that changes the code to fit different model(s) of modem, rather than lots of internal decision points.

After experimenting with other HTML parsers, I found some tricks that better-tolerate the weird differences in the devices' HTML (it's messy stuff), so now it's self-deciding based on the model number seen.

If folks send some files scraped from other models, I'll see about incorporating them, too.
(use 'curl 192.168.100.1 -o status.html' to capture, and also do so for the modem's page that has uptime - they seem to use different URLs by model.)
