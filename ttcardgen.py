#!/usr/bin/python3

from dataclasses import dataclass
from textwrap import wrap

import configparser
import argparse

import os
import sys
import io

import wand.drawing
import wand.image
import wand.color
import wand.font


DEFAULT_GRAVITY = "center"
DEFAULT_RESIZE = True
DEFAULT_TRIM = True
DEFAULT_BORDER = 20
DEFAULT_FONT_SIZE = 20
DEFAULT_BORDER_COLOUR = "black"
DEFAULT_TEXT_COLOUR = "black"

DEFAULT_SETTINGS = """
[Settings]
template_paths:
image_paths:
font_paths:
"""

DEFAULTCFG = """
[Card]
#template: templates/item.cfg
#background: card_background.png
#backside: card_backside.png
#border: 20
#border_colour: black
#image: items/fork.png
#title: A Fork
#text: Use this to eat spaghetti

[Image]
#area: x y width height
#resize: true
#trim: true
#gravity: center
#rotate: 30.6

[Title]
# Title accepts the same options as Text

[Text]
#area: x y width height
#font: fonts/textfont.ttf
#font_size: 20
#font_colour: black
#font_border_colour: black
#gravity: center
# the area is rotated around its center
#rotate: 30.6

[DEFAULT]
# these settings apply to all sections (can be overridden in section)
#font_size: 60
"""


settings = configparser.ConfigParser()
settings.read_string(DEFAULT_SETTINGS)


class CardError(Exception):
    pass


class CardConfigError(CardError):
    pass


class CardFileError(CardError):
    pass


printlevel = 1
"""
0 - only errors
1 - info
2 - verbose
3 - debug
"""

def printerror(msg):
    print(msg, file=sys.stderr)


def printinfo(msg):
    if printlevel >= 1:
        print(msg)


def printverbose(msg):
    if printlevel >= 2:
        print(msg)


def printdebug(msg):
    if printlevel >= 3:
        print(msg)


@dataclass
class Area:
    x: int
    y: int
    width: int
    height: int


class Card:

    def __init__(self, cfg):
        imgpath = cfg.get("background", None)
        if imgpath is None or imgpath == '':
            raise CardConfigError("background image not configured")

        bgimg = self._new_image(filename=imgpath)

        imgpath = cfg.get("backside", None)
        if imgpath is None or imgpath == '':
            backimg = None
        else:
            backimg = self._new_image(filename=imgpath)
            backimg.rotate(180)

        self._width = bgimg.width
        self._height = bgimg.height
        self._resolution = bgimg.resolution
        self._units = bgimg.units
        printdebug("background: %sx%s (%sdpi)" % (self._width, self._height, self._resolution))

        try:
            self._border_colour = wand.color.Color(cfg.get("border_colour", DEFAULT_BORDER_COLOUR))
        except ValueError as e:
            raise CardConfigError("invalid 'border_colour'") from e

        try:
            self._border = cfg.getint("border", fallback=DEFAULT_BORDER)
        except ValueError as e:
            raise CardConfigError("'border' must be a number") from e

        canvasheight = self._height + 2 * self._border
        if backimg is not None:
            canvasheight = 2 * canvasheight

        self._image = self._new_image(
            width=self._width + 2 * self._border,
            height=canvasheight,
            background=self._border_colour,
            resolution=bgimg.resolution,
        )

        self._image.composite(bgimg, self._border, self._border)
        cutmarks = self._draw_cutmarks()
        self._image.composite(cutmarks)

        if backimg is not None:
            if backimg.width != self._width or backimg.height != self._height:
                backimg.resize(self._width, self._height)
            self._image.composite(backimg, self._border, self._height + 3 * self._border)
            self._image.composite(cutmarks, 0, 2 * self._border + self._height)

    def _new_image(self, **kwargs):
        try:
            printdebug("new_image: %s" % kwargs)
            return wand.image.Image(**kwargs)
        except Exception as e:
            raise CardError("failed to create image: %s" % e) from e

    def _draw_cutmarks(self):
        marklen = self._border - 1
        if marklen <= 0:
            return

        image = self._new_image(
            width=self._width + 2 * self._border,
            height=self._height + 2 * self._border,
        )

        draw = wand.drawing.Drawing()
        draw.fill_color = self._border_colour
        draw.stroke_color = self._border_colour
        draw.stroke_width = 3

        hor_x = (0, self._border + self._width + 1)
        hor_y = (self._border - 1, self._border + self._height - 1)
        vert_x = (self._border - 1, self._border + self._width - 1)
        vert_y = (0, self._border + self._height + 1)

        for x in hor_x:
            for y in hor_y:
                draw.line((x, y), (x + marklen - 1, y))

        for x in vert_x:
            for y in vert_y:
                draw.line((x, y), (x, y + marklen - 1))

        draw(image)
        image.negate(False, 'rgb')
        return image

    def loadimage(self, filename, cfg_section):
        if len(filename) != 0:
            self.mergeimage(self._new_image(filename=filename), cfg_section)

    def mergeimage(self, image, cfg_section):
        try:
            area = CardConfig.str2area(cfg_section["area"])
        except KeyError as e:
            raise CardConfigError("'area' undefined ") from e
        canvas = self._new_image(width=area.width, height=area.height)
        img = image.clone()

        try:
            resize = cfg_section.getboolean("resize", fallback=DEFAULT_RESIZE)
        except ValueError as e:
            raise CardConfigError("'resize' must be a boolean") from e

        try:
            trim = cfg_section.getboolean("trim", fallback=DEFAULT_TRIM)
        except ValueError as e:
            raise CardConfigError("'trim' must be a boolean") from e

        try:
            rotate = cfg_section.getfloat("rotate", fallback=None)
        except ValueError as e:
            raise CardConfigError("'rotate' must be a real number") from e

        if rotate is not None:
            img.rotate(rotate)

        if trim:
            img.trim(color=None)

        if resize:
            img.transform(resize="%dx%d" % (area.width, area.height))

        canvas.composite(img, gravity=cfg_section.get("gravity", DEFAULT_GRAVITY))
        self._image.composite(canvas, self._border + area.x, self._border + area.y)

    def text(self, text, cfg_section):
        text = text.strip()
        if len(text) == 0:
            return

        try:
            area = CardConfig.str2area(cfg_section["area"])
        except KeyError as e:
            raise CardConfigError("'area' undefined") from e

        img = self._new_image(width=area.width, height=area.height)
        d = wand.drawing.Drawing()

        if "font" in cfg_section:
            d.font = cfg_section["font"]

        try:
            d.font_size = cfg_section.getint("font_size", fallback=DEFAULT_FONT_SIZE)
        except ValueError as e:
            raise CardConfigError("'font_size' must be a number") from e

        try:
            d.fill_color = wand.color.Color(cfg_section.get("font_colour", DEFAULT_TEXT_COLOUR))
            d.stroke_color = wand.color.Color(cfg_section.get("font_border_colour", DEFAULT_TEXT_COLOUR))
        except ValueError as e:
            raise CardConfigError("invalid 'font_colour'") from e

        try:
            rotate = cfg_section.getfloat("rotate", fallback=None)
        except ValueError as e:
            raise CardConfigError("'rotate' must be a real number") from e

        d.gravity = cfg_section.get("gravity", DEFAULT_GRAVITY)

        wrapped_text = Utils.word_wrap(img, d, text)

        printdebug("font_size: %s" % d.font_size)
        d.text(0, 0, wrapped_text)
        d.draw(img)

        comp_x = self._border + area.x
        comp_y = self._border + area.y

        if rotate is not None:
            img.rotate(rotate)
            # rotate around center
            comp_x += int((area.width - img.width)/2)
            comp_y += int((area.height - img.height)/2)
            printdebug("rotate %s %sx%s" % (rotate, comp_x, comp_y))

        self._image.composite(img, comp_x, comp_y)

    def save(self, filename):
        self._image.format = 'png'
        self._image.resolution = self._resolution
        self._image.save(filename=filename)


class CardConfig:

    def __init__(self, settings=settings):
        self.settings = settings
        self.cfg = configparser.ConfigParser()
        self.cfg.read_string(DEFAULTCFG)

    def __getitem__(self, key):
        if not self.cfg.has_section(key):
            raise CardConfigError("missing config section '%s'" % key)
        return self.cfg[key]

    def load(self, filename):
        printverbose("load config '%s'" % filename)

        cfgpath = os.path.realpath(filename)
        if not os.path.isfile(cfgpath):
            raise CardFileError("file not found: %s" % filename)

        cardconfig = configparser.ConfigParser()
        cardconfig.read(cfgpath)
        CardConfig.expand_paths(cardconfig, os.path.dirname(cfgpath), self.settings)

        try:
            templatepath = cardconfig["Card"]["template"]
        except KeyError:
            raise CardConfigError("template undefined")

        printverbose("using template '%s'" % templatepath)

        templatecfg = configparser.ConfigParser()
        templatecfg.read(templatepath)
        CardConfig.expand_paths(templatecfg, os.path.dirname(templatepath))

        self.cfg.read_dict(templatecfg)
        self.cfg.read_dict(cardconfig)

    def __str__(self):
        buf = io.StringIO()
        self.cfg.write(buf)
        return buf.getvalue()

    @staticmethod
    def str2area(txt):
        try:
            a = list(map(lambda x: int(x), txt.split()))
            return Area(a[0], a[1], a[2], a[3])
        except (ValueError, IndexError) as e:
            raise CardConfigError("error parsing area: %s" % txt) from e

    @staticmethod
    def find_file(filename, paths):
        if os.path.isabs(filename):
            return filename

        for p in paths:
            if os.path.isdir(p) and os.path.isabs(p):
                filepath = os.path.join(p, filename)
                if os.path.isfile(filepath):
                    return filepath
        return None

    @staticmethod
    def expand_paths(config, relpath, settings=settings):
        try:
            cfg = config["Card"]
        except KeyError as e:
            raise CardConfigError("missing config section: 'Card'")

        CardConfig.expand_paths_helper(cfg, ["background", "backside"], [relpath])

        imagekeys = list(filter(lambda x: x.startswith('image'), cfg.keys()))
        if len(imagekeys) > 0:
            paths = [relpath]
            paths.extend(settings["Settings"]["image_paths"].split())
            CardConfig.expand_paths_helper(cfg, imagekeys, paths)

        if "template" in cfg:
            paths = [relpath]
            paths.extend(settings["Settings"]["template_paths"].split())
            CardConfig.expand_paths_helper(cfg, ["template"], paths)

        for section in config.sections():
            if section.startswith("Title") or section.startswith("Text"):
                cfg = config[section]
                font = cfg.get("font", None)
                if font is not None and font.endswith(".ttf"):
                    paths = [relpath]
                    paths.extend(settings["Settings"]["font_paths"].split())
                    CardConfig.expand_paths_helper(cfg, ["font"], paths)

    @staticmethod
    def expand_paths_helper(cfg, keys, searchpaths):
        for k in keys:
            path = cfg.get(k, "")

            if len(path) == 0 or os.path.isabs(path):
                continue

            abspath = CardConfig.find_file(path, searchpaths)
            if abspath is None:
                raise CardFileError("%s: file not found %s" % (k, path))

            cfg[k] = abspath


class Utils:

    @staticmethod
    def word_wrap(image, ctx, text):
        """Break long text to multiple lines, and reduce point size
        until all text fits within a bounding box."""
        mutable_message = text
        lines = text.splitlines()
        maxcolumns = max(map(len, lines))
        iteration_attempts = 100

        def eval_metrics(txt):
            """Quick helper function to calculate width/height of text."""
            metrics = ctx.get_font_metrics(image, txt, True)
            return metrics.text_width, metrics.text_height

        while ctx.font_size > 0 and iteration_attempts:
            iteration_attempts -= 1
            width, height = eval_metrics(mutable_message)
            if height > image.height:
                ctx.font_size -= 0.75  # Reduce pointsize
                mutable_message = text  # Restore original text
            elif width > image.width:
                columns = maxcolumns
                while columns > 0:
                    columns -= 1
                    mutable_message = '\n'.join(map(lambda x: '\n'.join(wrap(x, columns)), lines))
                    wrapped_width, _ = eval_metrics(mutable_message)
                    if wrapped_width <= image.width:
                        break
                if columns < 1:
                    ctx.font_size -= 0.75  # Reduce pointsize
                    mutable_message = text  # Restore original text
            else:
                break
        if iteration_attempts < 1:
            raise CardError("unable to calculate word_wrap for " + text)
        return mutable_message


def load_settings():
    cfgpath = os.path.join(os.path.expanduser("~"), ".rpgcardgen.cfg")
    if os.path.isfile(cfgpath):
        settings.read(cfgpath)


def gencard(cfg):
    card = Card(cfg["Card"])

    for k in cfg["Card"].keys():
        try:
            if k.startswith("title") or k.startswith("text"):
                printverbose("adding text: %s" % k)
                card.text(cfg["Card"][k], cfg[k.capitalize()])

            elif k.startswith("image"):
                printverbose("adding image: %s" % k)
                card.loadimage(cfg["Card"][k], cfg[k.capitalize()])

        except CardError as e:
            raise CardError("%s: %s" % (k, e)) from e

    return card


def parseargs():

    parser = argparse.ArgumentParser()
    parser.add_argument("--example", action="store_true", help="print example config and exit")
    parser.add_argument("-f", action="store_true", help="overwrite output file")
    arggroup = parser.add_argument_group("output")
    arggroup.add_argument("-q", action="store_true", help="print only error messages")
    arggroup.add_argument("-v", action="store_true", help="verbose messages")
    arggroup.add_argument("-d", action="store_true", help="debug messages")
    parser.add_argument("config", help="card config file")
    parser.add_argument("output")
    return parser.parse_args()


if __name__ == '__main__':

    args = parseargs()

    if args.example:
        print(DEFAULTCFG)
        sys.exit(0)

    if not args.f and os.path.exists(args.output):
        printerror("Error: output already exists")
        sys.exit(1)

    if args.d:
        printlevel = 3
    elif args.v:
        printlevel = 2
    elif args.q:
        printlevel = 0

    load_settings()

    #sys.exit(0)

    try:
        cardcfg = CardConfig()
        cardcfg.load(args.config)
        printdebug(cardcfg)
        c = gencard(cardcfg)
        c.save(args.output)

    except CardConfigError as e:
        print("Config Error: %s" % e)
        sys.exit(1)

    except CardError as e:
        print("Error: %s" % e)
        sys.exit(1)

    sys.exit(0)


