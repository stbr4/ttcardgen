#!/usr/bin/python3

import unittest
import ttcardgen
import os
import configparser

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

defaultcfg = configparser.ConfigParser()
defaultcfg.read_string(ttcardgen.DEFAULTCFG)

defaultsettings = configparser.ConfigParser()
defaultsettings.read_string(ttcardgen.DEFAULT_SETTINGS)

def cfgcopy(cfg):
    newcfg = configparser.ConfigParser()
    newcfg.read_dict(cfg)
    return newcfg


class TestCfg(unittest.TestCase):

    def test_load_nonexitent(self):
        cfg = ttcardgen.CardConfig()
        with self.assertRaises(ttcardgen.CardFileError) as cm:
            cfg.load("test/nonexistent")

    def test_expand_path(self):
        cfg = cfgcopy(defaultcfg)

        with self.assertRaises(ttcardgen.CardFileError) as cm:
            cfg["Card"]["template"] = "test/nonexistent"
            ttcardgen.CardConfig.expand_paths(cfg, SCRIPT_DIR, defaultsettings)


if __name__ == '__main__':
    unittest.main()
