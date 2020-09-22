# ttcardgen

Card generator for tabletop or rpg games. This is still very much in beta but it should work.


# Install

```
apt install python3 python3-wand
```

# Usage

```
usage: ttcardgen.py [-h] [--example] [-f] [-q] [-v] [-d] config output

positional arguments:
  config      card config file
  output

optional arguments:
  -h, --help  show this help message and exit
  --example   print example config and exit
  -f          overwrite output file

output:
  -q          print only error messages
  -v          verbose messages
  -d          debug messages
```

Create the example card with the following command
```
./ttcardgen.py example/card.cfg card.png
```

Look at example/card.cfg and example/templates/cardtpl.cfg.
