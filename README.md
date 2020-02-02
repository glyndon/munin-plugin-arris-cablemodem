# munin-plugin-arris-cablemodem
Munin plugin(s) that will report the data available from an Arris cablemodem's web interface

The 'arris' file is an adaptation of a version forked from  bradh352's version (munin-plugins), and now heavily altered to bring it up-to-date, and to incorporate some features I've found useful.

The 'wan_json' file is my older effort that I'm migrating features from, into 'arris'

It's TBD which version I'll stick with ongoing; they both have their pro's/con's. The Soup parser is certainly easier to wrangle; the state machine in the arris version is faster and more clever, but also fragile.

My plan has been to create a git patch file that changes the code to fit different model(s) of modem, rather than lots of internal decision points. This too is subject to change.
