#!/usr/bin/python3
import collections.abc
from typing import Optional
from dataclasses import dataclass
from textwrap import wrap

from configparser import ConfigParser, SectionProxy
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
# use pango markup to render text
#text: PANGO:Use <b>this</b> to eat <i>spaghetti</i>

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
# pango can only use installed fonts
#font: DejaVu Serif
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


global_settings = ConfigParser()
global_settings.read_string(DEFAULT_SETTINGS)


class CardError(Exception):
    pass


class CardConfigError(CardError):
    pass


class CardFileError(CardError):
    pass


printlevel: int = 1
"""
0 - only errors
1 - info
2 - verbose
3 - debug
"""


def printerror(msg: str) -> None:
    print(msg, file=sys.stderr)


def printinfo(msg: str) -> None:
    if printlevel >= 1:
        print(msg)


def printverbose(msg: str) -> None:
    if printlevel >= 2:
        print(msg)


def printdebug(msg: str) -> None:
    if printlevel >= 3:
        print(msg)


@dataclass
class Area:
    x: int
    y: int
    width: int
    height: int


class CardConfig:

    def __init__(self, settings: ConfigParser = global_settings):
        self.settings = settings
        self.cfg = ConfigParser()
        self.cfg.read_string(DEFAULTCFG)

    def __getitem__(self, key: str) -> SectionProxy:
        if not self.cfg.has_section(key):
            raise CardConfigError("missing config section '%s'" % key)
        return self.cfg[key]

    def load(self, filename: str, level: int = 0) -> None:
        printverbose("load config '%s'" % filename)
        if level > 100:
            raise CardConfigError('too many templates')

        cfgpath = os.path.realpath(filename)
        if not os.path.isfile(cfgpath):
            raise CardFileError("file not found: %s" % filename)

        config = ConfigParser()
        config.read(cfgpath)

        try:
            config_card = config["Card"]
        except KeyError:
            raise CardConfigError("missing config section 'Card' from %s" % filename)

        CardConfig.expand_paths(config, os.path.dirname(cfgpath))

        if (templatepath := config_card.get('template', None)) is not None:
            self.load(templatepath, level + 1)

        self.cfg.read_dict(config)

    def __str__(self) -> str:
        buf = io.StringIO()
        self.cfg.write(buf)
        return buf.getvalue()

    @staticmethod
    def str2area(txt: str) -> Area:
        try:
            a = list(map(lambda x: int(x), txt.split()))
            return Area(a[0], a[1], a[2], a[3])
        except (ValueError, IndexError) as err:
            raise CardConfigError("error parsing area: %s" % txt) from err

    @staticmethod
    def find_file(filename: str, paths: list[str]) -> Optional[str]:
        if os.path.isabs(filename):
            return filename

        for p in paths:
            if os.path.isdir(p) and os.path.isabs(p):
                filepath = os.path.join(p, filename)
                if os.path.isfile(filepath):
                    return filepath
        return None

    @staticmethod
    def expand_paths(config: ConfigParser, relpath: str) -> None:
        try:
            cfg = config["Card"]
        except KeyError:
            raise CardConfigError("missing config section: 'Card'")

        filekeys = ['template', 'background', 'backside']
        filekeys.extend(list(filter(lambda x: x.startswith('image'), cfg.keys())))
        for key in filekeys:
            path: str = cfg.get(key, "")
            if len(path) > 0:
                cfg[key] = os.path.join(relpath, path)

        for section in config.sections():
            if section.startswith("Title") or section.startswith("Text"):
                path = config[section].get("font", "")
                if len(path) > 0:
                    config[section]['fong'] = os.path.join(relpath, path)

    @staticmethod
    def expand_paths_helper(cfg_section: SectionProxy, keys: list[str], searchpaths: list[str]):
        for k in keys:
            path: str = cfg_section.get(k, "")

            if len(path) == 0 or os.path.isabs(path):
                continue

            abspath = CardConfig.find_file(path, searchpaths)
            if abspath is None:
                raise CardFileError("%s: file not found %s" % (k, path))

            cfg_section[k] = abspath


class Card:

    def __init__(self, cardconfig: CardConfig):
        self.cardconfig = cardconfig

        try:
            cfg = cardconfig["Card"]
        except KeyError:
            raise CardConfigError("missing config section: 'Card'")

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
            #self._border_colour_back = wand.color.Color(cfg.get("border_colour_back", self._border_colour))
        except ValueError as err:
            raise CardConfigError("invalid 'border_colour'") from err

        try:
            self._border = cfg.getint("border", fallback=DEFAULT_BORDER)
        except ValueError as err:
            raise CardConfigError("'border' must be a number") from err

        canvasheight = self._height + 2 * self._border
        if backimg is not None:
            canvasheight = 2 * canvasheight

        self._image = self._new_image(
            width=self._width + 2 * self._border,
            height=canvasheight,
            background=self._border_colour,
            units=bgimg.units,
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

    @staticmethod
    def _new_image(**kwargs) -> wand.image.Image:
        try:
            printdebug("new_image: %s" % kwargs)
            return wand.image.Image(**kwargs)
        except Exception as err:
            raise CardError("failed to create image: %s" % err) from err

    def _draw_cutmarks(self) -> wand.image.Image:
        image = self._new_image(
            width=self._width + 2 * self._border,
            height=self._height + 2 * self._border,
        )

        marklen = self._border - 1
        if marklen <= 0:
            return image

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

    def merge_image(self, key: str) -> None:
        filename = self.cardconfig['Card'][key]
        if len(filename) == 0:
            return

        printverbose("merge image: %s" % filename)

        # TODO: catch section not found
        image_settings = self.cardconfig[key.capitalize()]

        image = self._new_image(filename=filename)

        try:
            area = CardConfig.str2area(image_settings["area"])
        except KeyError as err:
            raise CardConfigError("'area' undefined ") from err
        canvas = self._new_image(width=area.width, height=area.height)
        img = image.clone()  # TODO: why?

        try:
            resize = image_settings.getboolean("resize", fallback=DEFAULT_RESIZE)
        except ValueError as err:
            raise CardConfigError("'resize' must be a boolean") from err

        try:
            trim = image_settings.getboolean("trim", fallback=DEFAULT_TRIM)
        except ValueError as err:
            raise CardConfigError("'trim' must be a boolean") from err

        try:
            rotate = image_settings.getfloat("rotate", fallback=None)
        except ValueError as err:
            raise CardConfigError("'rotate' must be a real number") from err

        if rotate is not None:
            img.rotate(rotate)

        if trim:
            img.trim()

        if resize:
            img.transform(resize="%dx%d" % (area.width, area.height))

        canvas.composite(img, gravity=image_settings.get("gravity", DEFAULT_GRAVITY))
        self._image.composite(canvas, self._border + area.x, self._border + area.y)

    def text(self, key: str) -> None:
        text = self.cardconfig['Card'][key].strip()
        if len(text) == 0:
            return

        text_settings = self.cardconfig[key.capitalize()]

        try:
            area = CardConfig.str2area(text_settings['area'])
        except KeyError as err:
            raise CardConfigError("'area' undefined") from err

        img = self._new_image(width=area.width, height=area.height)
        drawing = wand.drawing.Drawing()

        if 'font' in text_settings:
            drawing.font = text_settings['font']

        try:
            drawing.font_size = text_settings.getint('font_size', fallback=DEFAULT_FONT_SIZE)
        except ValueError as err:
            raise CardConfigError("'font_size' must be a number") from err

        try:
            drawing.fill_color = wand.color.Color(text_settings.get('font_colour', DEFAULT_TEXT_COLOUR))
            drawing.stroke_color = wand.color.Color(text_settings.get('font_border_colour', DEFAULT_TEXT_COLOUR))
        except ValueError as err:
            raise CardConfigError("invalid 'font_colour'") from err

        try:
            rotate = text_settings.getfloat('rotate', fallback=None)
        except ValueError as err:
            raise CardConfigError("'rotate' must be a real number") from err

        drawing.gravity = text_settings.get('gravity', DEFAULT_GRAVITY)

        wrapped_text = Utils.word_wrap(img, drawing, text)

        printdebug('font_size: %s' % drawing.font_size)
        drawing.text(0, 0, wrapped_text)
        drawing.draw(img)

        comp_x = self._border + area.x
        comp_y = self._border + area.y

        if rotate is not None:
            img.rotate(rotate)
            # rotate around center
            comp_x += int((area.width - img.width)/2)
            comp_y += int((area.height - img.height)/2)
            printdebug('rotate %s %sx%s' % (rotate, comp_x, comp_y))

        self._image.composite(img, comp_x, comp_y)

    def pango(self, text: str, cfg_section: SectionProxy):
        text = text.strip()
        if len(text) == 0:
            return

        try:
            area = CardConfig.str2area(cfg_section["area"])
        except KeyError as err:
            raise CardConfigError("'area' undefined") from err

        span = cfg_section.get("span", "")

        span_opts = []
        if "font" in cfg_section:
            span_opts.append("font=\"%s\"" % cfg_section.get("font"))
        try:
            span_opts.append("size=\"%i\"" % (cfg_section.getfloat("font_size", fallback=DEFAULT_FONT_SIZE) * 1000))
        except ValueError as err:
            raise CardConfigError("'font_size' must be a real number") from err
        span_opts.append("foreground=\"%s\"" % cfg_section.get("font_colour", DEFAULT_TEXT_COLOUR))

        try:
            rotate = cfg_section.getfloat("rotate", fallback=None)
        except ValueError as err:
            raise CardConfigError("'rotate' must be a real number") from err

        gravity = cfg_section.get("gravity", DEFAULT_GRAVITY)
        if gravity.endswith("east"):
            pangogravity = "west"
        elif gravity.endswith("west"):
            pangogravity = "east"
        else:
            pangogravity = "center"

        pangotext = ''.join(["pango:<span ", ' '.join(span_opts), ">", text, "</span>"])
        printdebug(pangotext)
        pangoimg = self._new_image(resolution=(300.0, 300.0))
        pangoimg.gravity = pangogravity
        pangoimg.read(filename=pangotext, width=area.width, height=area.height, background="transparent")
        pangoimg.trim()

        img = self._new_image(width=area.width, height=area.height)
        img.composite(pangoimg, gravity=gravity)

        comp_x = self._border + area.x
        comp_y = self._border + area.y

        if rotate is not None:
            img.rotate(rotate)
            # rotate around center
            comp_x += int((area.width - img.width)/2)
            comp_y += int((area.height - img.height)/2)
            printdebug("rotate %s %sx%s" % (rotate, comp_x, comp_y))

        self._image.composite(img, comp_x, comp_y)

    def save(self, filename: str) -> None:
        self._image.format = 'png'
        self._image.resolution = self._resolution
        self._image.save(filename=filename)


class Utils:

    @staticmethod
    def word_wrap(image: wand.image.Image, ctx: wand.drawing.Drawing, text: str) -> str:
        """Break long text to multiple lines, and reduce point size
        until all text fits within a bounding box."""
        mutable_message = text
        lines = text.splitlines()
        maxcolumns = max(map(len, lines))
        iteration_attempts = 100

        def eval_metrics(txt: str) -> (int, int):
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


def load_settings() -> None:
    cfgpath = os.path.join(os.path.expanduser("~"), ".rpgcardgen.cfg")
    if os.path.isfile(cfgpath):
        global_settings.read(cfgpath)


def gencard(config: CardConfig) -> Card:
    card = Card(config)

    for k in config["Card"].keys():
        try:
            if k.startswith("title") or k.startswith("text"):
                printverbose("adding text: %s" % k)
                text = config["Card"][k]
                if text.startswith("PANGO:"):
                    card.pango(text[6:], config[k.capitalize()])
                else:
                    card.text(k)

            elif k.startswith("image"):
                printverbose("adding image: %s" % k)
                card.merge_image(k)

            elif k.startswith("pango"):
                printverbose("adding pango: %s" % k)
                card.pango(config["Card"][k], config[k.capitalize()])

        except CardError as err:
            raise CardError("%s: %s" % (k, err)) from err

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
        printdebug(str(cardcfg))
        c = gencard(cardcfg)
        c.save(args.output)

    except CardConfigError as e:
        print("Config Error: %s" % e)
        sys.exit(1)

    except CardError as e:
        print("Error: %s" % e)
        sys.exit(1)

    sys.exit(0)
