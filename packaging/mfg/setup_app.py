#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Setup's desktop app on GTK 4 and libadwaita: the game library first, each game's page with its state and the actions
that state allows, and every change run as an install.py command with its progress, outcome and output in view.

setup.py starts it when PyGObject, GTK 4 and libadwaita 1.5 or newer are installed; otherwise Setup keeps its Zenity
dialogs. setup_model.py decides what each page says and which command each choice runs; this module draws it, keeps
the window responsive (reads run off its thread, one at a time; install.py runs in its own processes) and asks before
anything that is hard to undo.
"""
import concurrent.futures
import os
import re
import subprocess
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

import setup_model as model  # noqa: E402

# Adw.Dialog, Adw.AlertDialog and Adw.AboutDialog are 1.5's; Setup falls back to Zenity below it.
if (Adw.get_major_version(), Adw.get_minor_version()) < (1, 5):
    raise ImportError('Setup’s window needs libadwaita 1.5 or newer')

CSS = '''
.badge { padding: 1px 9px; border-radius: 999px; font-size: 0.78em; font-weight: 700; }
.badge.accent { background-color: alpha(@accent_bg_color, 0.18); color: @accent_color; }
.badge.success { background-color: alpha(@success_color, 0.16); color: @success_color; }
.badge.warning { background-color: alpha(@warning_color, 0.20); color: @warning_color; }
.badge.error { background-color: alpha(@error_color, 0.16); color: @error_color; }
.badge.dim { background-color: alpha(currentColor, 0.09); color: alpha(currentColor, 0.70); }
.hero { padding: 18px 20px; }
.hero-icon { border-radius: 999px; padding: 14px; }
.hero-icon.success { background-color: alpha(@success_color, 0.16); color: @success_color; }
.hero-icon.accent { background-color: alpha(@accent_bg_color, 0.18); color: @accent_color; }
.hero-icon.warning { background-color: alpha(@warning_color, 0.20); color: @warning_color; }
.hero-icon.error { background-color: alpha(@error_color, 0.16); color: @error_color; }
.hero-icon.neutral { background-color: alpha(currentColor, 0.08); }
.headline.success { color: @success_color; }
.headline.accent { color: @accent_color; }
.headline.warning { color: @warning_color; }
.headline.error { color: @error_color; }
.sidebar-section { font-size: 0.8em; font-weight: 700; margin: 14px 12px 4px 12px; opacity: 0.6; }
.log-view { font-family: monospace; font-size: 0.86em; }
.log-view text { background-color: transparent; }
.step-number { font-weight: 800; min-width: 22px; opacity: 0.6; }
.path { font-family: monospace; font-size: 0.86em; }
.dim { opacity: 0.6; }
'''

STATE_ICONS = {'recovery': ('dialog-error-symbolic', 'error'), 'attention': ('dialog-warning-symbolic', 'warning'),
               'unavailable': ('action-unavailable-symbolic', 'dim'), 'update': ('software-update-available-symbolic', 'accent'),
               'outdated': ('dialog-warning-symbolic', 'warning'), 'newer': ('emblem-ok-symbolic', 'dim'),
               'pinned': ('changes-prevent-symbolic', 'dim'), 'installed': ('emblem-ok-symbolic', 'success'),
               'available': ('applications-games-symbolic', 'dim')}
LEVEL_ICONS = {'success': 'emblem-ok-symbolic', 'accent': 'software-update-available-symbolic',
               'warning': 'dialog-warning-symbolic', 'error': 'dialog-error-symbolic', 'neutral': 'dialog-information-symbolic',
               'dim': 'action-unavailable-symbolic'}
DOCTOR_LEVELS = {'OK': 'success', 'WARN': 'warning', 'INFO': 'neutral'}


# ------------------------------------------------------------------------------------------------- small widgets
def esc(text):
    return GLib.markup_escape_text(str(text if text is not None else ''))


def text_label(text='', classes=(), wrap=False, xalign=0.0, ellipsize=False, selectable=False, lines=0):
    widget = Gtk.Label(label=str(text), xalign=xalign, selectable=selectable)
    if wrap:
        widget.set_wrap(True)
        widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if ellipsize:
        widget.set_ellipsize(Pango.EllipsizeMode.END)
    if lines:
        widget.set_lines(lines)
    for name in classes:
        widget.add_css_class(name)
    return widget


def bar_text(text='', classes=()):
    """Text in a dialog's bottom bar, with room for two lines at every width: a wrapping label there loses its second
    line when a narrow window makes the dialog narrower than its content width."""
    widget = Gtk.Inscription(text=text, min_lines=2, nat_lines=2, xalign=0.5, hexpand=True,
                             wrap_mode=Pango.WrapMode.WORD_CHAR, text_overflow=Gtk.InscriptionOverflow.ELLIPSIZE_END)
    for name in classes:
        widget.add_css_class(name)
    return widget


def tint(widget, level):
    """Colour an icon or label by level (libadwaita's success, warning, error and accent classes; dim for the rest)."""
    if level in ('success', 'warning', 'error', 'accent'):
        widget.add_css_class(level)
    elif level == 'dim':
        widget.add_css_class('dim-label')
    return widget


def icon(name, level=None, size=None):
    image = Gtk.Image(icon_name=name)
    if size:
        image.set_pixel_size(size)
    return tint(image, level)


def badge(text, style):
    widget = Gtk.Label(label=text, valign=Gtk.Align.CENTER)
    widget.add_css_class('badge')
    widget.add_css_class(style)
    return widget


def plain(row, title, subtitle=None, lines=0):
    """A libadwaita row with title and subtitle as plain text (rows read Pango markup by default; game names and the
    installer's messages are not markup)."""
    row.set_use_markup(False)
    row.set_title(str(title))
    if hasattr(row, 'set_title_lines'):
        row.set_title_lines(lines)
    if subtitle:
        row.set_subtitle(str(subtitle))
        if hasattr(row, 'set_subtitle_lines'):
            row.set_subtitle_lines(lines)
    return row


def action_row(title, subtitle=None, icon_name=None, level=None):
    row = plain(Adw.ActionRow(), title, subtitle)
    if icon_name:
        row.add_prefix(icon(icon_name, level))
    return row


def button(text, callback, *styles, icon_name=None, tooltip=None):
    widget = Gtk.Button(valign=Gtk.Align.CENTER)
    if icon_name and not text:
        widget.set_icon_name(icon_name)
    elif icon_name:
        widget.set_child(Adw.ButtonContent(icon_name=icon_name, label=text, use_underline=True))
    else:
        widget.set_label(text)
        widget.set_use_underline(True)
    for style in styles:
        widget.add_css_class(style)
    if tooltip:
        widget.set_tooltip_text(tooltip)
    widget.connect('clicked', lambda *_: callback())
    return widget


def group(title=None, description=None, suffix=None):
    widget = Adw.PreferencesGroup()
    if title:
        widget.set_title(esc(title))
    if description:
        widget.set_description(esc(description))
    if suffix is not None:
        widget.set_header_suffix(suffix)
    return widget


def spinner():
    widget = Gtk.Spinner(spinning=True, valign=Gtk.Align.CENTER)
    return widget


def hero(title, level, headline, description, primary=None, secondary=None, icon_name=None):
    """The card at the top of a page: an icon tinted by level, the title, what matters now and the main action."""
    card = Gtk.Box(spacing=18)
    card.add_css_class('card')
    card.add_css_class('hero')
    badge_icon = icon(icon_name or LEVEL_ICONS.get(level, 'dialog-information-symbolic'), size=32)
    badge_icon.add_css_class('hero-icon')
    badge_icon.add_css_class(level if level in ('success', 'accent', 'warning', 'error') else 'neutral')
    badge_icon.set_valign(Gtk.Align.CENTER)
    card.append(badge_icon)
    texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True, valign=Gtk.Align.CENTER)
    texts.append(text_label(title, ['title-2'], wrap=True))
    line = text_label(headline, ['heading', 'headline'], wrap=True)
    if level in ('success', 'accent', 'warning', 'error'):
        line.add_css_class(level)
    texts.append(line)
    if description:
        texts.append(text_label(description, ['dim-label'], wrap=True))
    card.append(texts)
    buttons = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, valign=Gtk.Align.CENTER)
    for widget in (primary, secondary):
        if widget is not None:
            buttons.append(widget)
    if primary is not None or secondary is not None:
        card.append(buttons)
    return card


def numbered(steps):
    """Rows for numbered steps (the player's own steps after an installation)."""
    rows = []
    for number, step in enumerate(steps, 1):
        row = plain(Adw.ActionRow(), step)
        row.add_prefix(text_label(str(number), ['step-number'], xalign=0.5))
        rows.append(row)
    return rows


def log_view():
    view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                        top_margin=8, bottom_margin=8, left_margin=10, right_margin=10)
    view.add_css_class('log-view')
    scrolled = Gtk.ScrolledWindow(child=view, vexpand=True, min_content_height=180)
    scrolled.add_css_class('card')
    return view, scrolled


def append_text(view, text):
    buffer = view.get_buffer()
    buffer.insert(buffer.get_end_iter(), text)
    mark = buffer.create_mark(None, buffer.get_end_iter(), False)
    view.scroll_to_mark(mark, 0.0, False, 0.0, 1.0)
    buffer.delete_mark(mark)


def copy_text(widget, text):
    widget.get_clipboard().set(text)


# ------------------------------------------------------------------------------------------------- work off the window
class Reader:
    """Runs the model's reads off the window's thread, one at a time (the installer's module is not written for
    threads), and hands each result back on the window's thread. probe runs the system check, a process of its own,
    beside them."""

    def __init__(self):
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix='setup-read')
        self.probes = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix='setup-probe')

    def call(self, function, *args, done=None, failed=None, probe=False):
        future = (self.probes if probe else self.pool).submit(function, *args)
        future.add_done_callback(lambda f: GLib.idle_add(self._deliver, f, done, failed))
        return future

    @staticmethod
    def _deliver(future, done, failed):
        try:
            result = future.result()
        except Exception as error:  # noqa: BLE001 - a read that fails is shown, never a crash of the window
            if failed is not None:
                failed(error)
            else:
                traceback.print_exception(error)
        else:
            if done is not None:
                done(result)
        return GLib.SOURCE_REMOVE


@dataclass
class Step:
    """One install.py command of an operation, for one game (game None: Setup-wide, as HLX preparation)."""
    title: str
    args: list
    game: object = None


@dataclass
class Result:
    step: Step
    returncode: int = None
    lines: list = field(default_factory=list)

    @property
    def ok(self):
        return self.returncode == 0


class Operation:
    """install.py commands one after another, each in its own process, their output handed to the window as it comes.
    stop() lets the command running finish and skips the rest: the installer's transactions are never cut short."""

    def __init__(self, ctx, steps, on_line=None, on_step=None, on_done=None):
        self.ctx, self.steps = ctx, steps
        self.on_line, self.on_step, self.on_done = on_line, on_step, on_done
        self.stopping = False
        self.running = False

    def start(self):
        self.running = True
        threading.Thread(target=self._run, name='setup-operation', daemon=True).start()

    def stop(self):
        self.stopping = True

    def _post(self, callback, *args):
        if callback is not None:
            GLib.idle_add(lambda: (callback(*args), GLib.SOURCE_REMOVE)[1])

    def _run(self):
        results = []
        environment = dict(os.environ, PYTHONIOENCODING='utf-8')
        for index, step in enumerate(self.steps):
            result = Result(step)
            results.append(result)
            if self.stopping:
                continue
            self._post(self.on_step, index, step)
            try:
                process = subprocess.Popen(self.ctx.command(step.args), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace',
                                           env=environment)
            except OSError as error:
                result.returncode, result.lines = 1, [('err', 'Setup could not start the installer: ' + str(error))]
                self._post(self.on_line, index, 'err', result.lines[0][1])
                continue

            def pump(stream, name):
                for line in stream:
                    line = line.rstrip('\n')
                    result.lines.append((name, line))
                    self._post(self.on_line, index, name, line)
            with process:  # closes its pipes once both are read
                readers = [threading.Thread(target=pump, args=(process.stdout, 'out'), daemon=True),
                           threading.Thread(target=pump, args=(process.stderr, 'err'), daemon=True)]
                for reader in readers:
                    reader.start()
                for reader in readers:
                    reader.join()
                result.returncode = process.wait()
        self.running = False
        self._post(self.on_done, results)


# ------------------------------------------------------------------------------------------------- the operation dialog
class OperationDialog(Adw.Dialog):
    """Runs an operation in view: what it is doing now, how far it got, then what came of it for each game, the
    player's next steps and the installer's full output. Closing waits for the operation (Stop skips what has not
    started)."""

    def __init__(self, window, title, steps, working, success, next_steps=(), on_finished=None):
        super().__init__(title=title, content_width=640, content_height=500)
        self.window, self.steps, self.success = window, steps, success
        self.extra_steps, self.on_finished = list(next_steps), on_finished
        self.results = []
        self.set_can_close(False)
        self.connect('close-attempt', lambda *_: window.toast('Setup finishes the current step first.'))
        view = Adw.ToolbarView()
        self.header = Adw.HeaderBar(show_end_title_buttons=False)
        view.add_top_bar(self.header)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin_top=18, margin_bottom=18,
                          margin_start=22, margin_end=22)
        top = Gtk.Box(spacing=16)
        self.status_icon = Gtk.Stack()
        self.status_icon.add_named(Gtk.Spinner(spinning=True, width_request=40, height_request=40), 'busy')
        self.status_icon.add_named(Gtk.Image(pixel_size=40), 'done')
        top.append(self.status_icon)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        self.title_label = text_label(working, ['title-3'], wrap=True)
        self.detail_label = text_label('', ['dim-label'], ellipsize=True)
        texts.append(self.title_label)
        texts.append(self.detail_label)
        top.append(texts)
        content.append(top)
        self.progress = Gtk.ProgressBar(show_text=len(steps) > 1)
        content.append(self.progress)
        self.outcome = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, visible=False)
        content.append(self.outcome)
        self.expander = Gtk.Expander(label='Installer output', expanded=False)
        self.log, scrolled = log_view()
        self.expander.set_child(scrolled)
        content.append(self.expander)
        scroller = Gtk.ScrolledWindow(child=content, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        view.set_content(scroller)
        bottom = Gtk.Box(spacing=8, margin_top=10, margin_bottom=10, margin_start=12, margin_end=12)
        bottom.append(button('_Copy Output', self.copy, 'flat', icon_name='edit-copy-symbolic'))
        bottom.append(Gtk.Box(hexpand=True))
        self.stop_button = button('_Stop After This Game', self.stop)
        self.stop_button.set_visible(len(steps) > 1)
        bottom.append(self.stop_button)
        self.done_button = button('_Done', self.close_done, 'suggested-action')
        self.done_button.set_visible(False)
        bottom.append(self.done_button)
        view.add_bottom_bar(bottom)
        self.set_child(view)
        self.pulse = GLib.timeout_add(120, self._pulse)
        self.operation = Operation(window.ctx, steps, self._line, self._step, self._done)
        window.busy(True)

    def start(self):
        self.present(self.window)
        self.operation.start()

    def _pulse(self):
        if len(self.steps) == 1:
            self.progress.pulse()
        return GLib.SOURCE_CONTINUE

    def _step(self, index, step):
        if len(self.steps) > 1:
            self.progress.set_fraction(index / len(self.steps))
            self.progress.set_text(f'{index + 1} of {len(self.steps)}: {step.title}')
        append_text(self.log, ('\n' if index else '') + '— ' + step.title + ' —\n')

    def _line(self, index, stream, line):
        append_text(self.log, line + '\n')
        if line.strip():
            self.detail_label.set_text(line.strip())

    def stop(self):
        self.operation.stop()
        self.stop_button.set_sensitive(False)
        self.stop_button.set_label('Stopping after this game…')

    def copy(self):
        buffer = self.log.get_buffer()
        copy_text(self, buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False))
        self.window.toast('Installer output copied')

    def _done(self, results):
        GLib.source_remove(self.pulse)
        self.results = results
        self.window.busy(False)
        self.set_can_close(True)
        self.header.set_show_end_title_buttons(True)
        self.stop_button.set_visible(False)
        self.done_button.set_visible(True)
        self.done_button.grab_focus()
        self.progress.set_visible(False)
        ran = [r for r in results if r.returncode is not None]
        failed = [r for r in ran if not r.ok]
        skipped = [r for r in results if r.returncode is None]
        if not failed and not skipped:
            level, title = 'success', self.success
        elif len(failed) == len(results):
            level, title = 'error', ('That did not complete' if len(results) == 1 else 'None of these completed')
        else:
            level, title = 'warning', f'{len(ran) - len(failed)} of {len(results)} completed'
        image = self.status_icon.get_child_by_name('done')
        image.set_from_icon_name(LEVEL_ICONS[level])
        tint(image, level)
        self.status_icon.set_visible_child_name('done')
        self.title_label.set_text(title)
        if failed and len(results) == 1:
            self.detail_label.set_text(model.failure_reason(failed[0].lines))
            self.detail_label.set_ellipsize(Pango.EllipsizeMode.NONE)
            self.detail_label.set_wrap(True)
            self.detail_label.remove_css_class('dim-label')
        else:
            self.detail_label.set_text('')
        if len(results) > 1:
            listing = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
            listing.add_css_class('boxed-list')
            for result in results:
                if result.returncode is None:
                    row = action_row(result.step.title, 'Not started (stopped)', 'action-unavailable-symbolic', 'dim')
                elif result.ok:
                    row = action_row(result.step.title, self.done_line(result), 'emblem-ok-symbolic', 'success')
                else:
                    row = action_row(result.step.title, model.failure_reason(result.lines), 'dialog-warning-symbolic', 'warning')
                listing.append(row)
            self.outcome.append(listing)
        changes = model.summary_lines(ran[0].lines)[:8] if len(results) == 1 and ran and not failed else []
        if changes:
            self.outcome.append(text_label('What changed', ['heading']))
            listing = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
            listing.add_css_class('boxed-list')
            for line in changes:
                listing.append(plain(Adw.ActionRow(), line))
            self.outcome.append(listing)
        steps = []
        if not failed:
            steps = list(dict.fromkeys([*self.extra_steps, *[s for r in ran for s in model.next_steps(r.lines)]]))
        if steps:
            self.outcome.append(text_label('Your next steps', ['heading']))
            listing = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
            listing.add_css_class('boxed-list')
            for row in numbered(steps):
                listing.append(row)
            self.outcome.append(listing)
        if failed:
            self.expander.set_expanded(len(results) == 1)
        self.outcome.set_visible(bool(self.outcome.get_first_child()))
        if self.on_finished is not None:
            self.on_finished(results)

    @staticmethod
    def done_line(result):
        for _, line in reversed(result.lines):
            found = re.match(r'Updated to (\S+)\.(?:\s|$)', line.strip())
            if found:
                return 'Updated to ' + model.version(found[1])
        return 'Done'

    def close_done(self):
        self.close()


# ------------------------------------------------------------------------------------------------- text reports
class TextDialog(Adw.Dialog):
    """An install.py report (Status, Check) in a readable, copyable view."""

    def __init__(self, window, title, args, intro=None):
        super().__init__(title=title, content_width=760, content_height=600)
        self.window = window
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.copy_button = button('', self.copy, 'flat', icon_name='edit-copy-symbolic', tooltip='Copy')
        self.copy_button.set_sensitive(False)
        header.pack_start(self.copy_button)
        view.add_top_bar(header)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=16, margin_start=16,
                      margin_end=16)
        if intro:
            box.append(text_label(intro, ['dim-label'], wrap=True))
        self.view, scrolled = log_view()
        box.append(scrolled)
        view.set_content(box)
        self.set_child(view)
        self.lines = []
        Operation(window.ctx, [Step(title, args)], on_line=self._line, on_done=self._done).start()

    def _line(self, index, stream, line):
        self.lines.append(line)
        append_text(self.view, line + '\n')

    def _done(self, results):
        self.copy_button.set_sensitive(True)

    def copy(self):
        copy_text(self, '\n'.join(self.lines).strip() + '\n')
        self.window.toast('Copied')


# ------------------------------------------------------------------------------------------------- install
class InstallDialog(Adw.Dialog):
    """Install for one game: its compatibility for the input chosen, the upscaler, the refusals that need the player's
    explicit yes, the steps they take after, and what Setup changes. risk_sentence: the anti-cheat override, confirmed
    for this game."""

    def __init__(self, window, game, risk_sentence=None):
        super().__init__(title='Install ' + window.ctx.name, content_width=660, content_height=760)
        self.window, self.game, self.ctx = window, game, window.ctx
        self.risk_sentence = risk_sentence
        self.verdict, self.checking, self.generation = None, True, 0
        self.providers = window.providers
        self.accepted = {}
        view = Adw.ToolbarView()
        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        header.pack_start(button('_Cancel', self.close))
        self.install_button = button('_Install', self.install, 'suggested-action')
        header.pack_end(self.install_button)
        header.set_title_widget(Adw.WindowTitle(title='Install ' + self.ctx.name, subtitle=game.title))
        view.add_top_bar(header)
        self.banner = Adw.Banner(button_label='_Check Again', revealed=False)
        self.banner.connect('button-clicked', lambda *_: self.install())
        view.add_top_bar(self.banner)
        page = Adw.PreferencesPage()
        self.verdict_group = group('Compatibility')
        self.verdict_rows = []
        page.add(self.verdict_group)
        self.soft_group = group('Needs your OK', 'Install refuses these unless you accept them for this game.')
        self.soft_group.set_visible(False)
        self.soft_rows = []
        page.add(self.soft_group)
        self.risk_group = group('Anti-cheat')
        self.risk_group.set_visible(bool(risk_sentence))
        if risk_sentence:
            self.risk_group.add(action_row('The anti-cheat refusal is overridden for this game only',
                                           'At the risk of an account ban. Status and Check show it until Restore.',
                                           'dialog-warning-symbolic', 'error'))
        page.add(self.risk_group)
        inputs = group('Frame-generation input', 'Prefer the game’s own frame generation when it has one. Every input '
                                                 'generates with XeFG; frame generation is 2×.')
        self.input_row = plain(Adw.ComboRow(), 'Input')
        self.input_row.set_model(Gtk.StringList.new([label for _, label, _ in model.INPUTS]))
        self.input_row.set_subtitle(model.INPUTS[0][2])
        self.input_row.connect('notify::selected', lambda *_: self.input_changed())
        inputs.add(self.input_row)
        page.add(inputs)
        self.provider_group = group('Upscaler', 'You can switch it later on the game’s page.')
        self.provider_rows = {}
        self.credit = text_label(self.ctx.helix_about, ['dim-label', 'caption'], wrap=True)
        self.credit.set_margin_top(10)
        self.credit.set_visible(False)
        self.provider_group.add(self.credit)
        page.add(self.provider_group)
        self.steps_group = group('After installing', 'Reopen your launcher and play normally. In the game:')
        self.steps_rows = []
        page.add(self.steps_group)
        changes = group('What Setup changes')
        about = plain(Adw.ExpanderRow(), 'Files, launch settings and downloads',
                      'Every replaced file is backed up; Restore returns them.')
        about.add_row(plain(Adw.ActionRow(), 'The first installation downloads checked upstream files: AMD FSR 4 and '
                            'Intel’s XeFG runtime. A fresh OptiScaler setup also fetches OptiScaler and OptiPatcher, and '
                            'NVIDIA’s DLSS helper only for a DLSS input where OptiScaler finds no copy of the game’s own.'))
        about.add_row(plain(Adw.ActionRow(), 'Setup configures the game’s launch settings in Steam, Heroic or Lutris and '
                            'keeps your own launch options. Close the game and its launcher before installing.'))
        changes.add(about)
        page.add(changes)
        self.hint = bar_text(classes=['dim-label'])
        hint_box = Gtk.Box(margin_top=8, margin_bottom=10, margin_start=16, margin_end=16)
        hint_box.append(self.hint)
        view.add_bottom_bar(hint_box)
        view.set_content(page)
        self.set_child(view)
        self.build_providers()
        window.providers_listeners.append(self.providers_changed)
        self.connect('closed', lambda *_: window.providers_listeners.remove(self.providers_changed))
        self.recheck()

    @property
    def input_id(self):
        return model.INPUTS[self.input_row.get_selected()][0]

    def input_changed(self):
        self.input_row.set_subtitle(model.INPUTS[self.input_row.get_selected()][2])
        self.recheck()

    def recheck(self):
        self.checking = True
        self.generation += 1
        generation = self.generation
        self.update_state()
        risk = ['anticheat'] if self.risk_sentence else []
        self.window.reader.call(model.check_game, self.ctx, self.game.exe, self.input_id, risk,
                                done=lambda verdict: self.checked(generation, verdict))

    def checked(self, generation, verdict):
        if generation != self.generation:
            return
        self.verdict, self.checking = verdict, False
        for row in self.verdict_rows:
            self.verdict_group.remove(row)
        self.verdict_rows = []
        rows = []
        if not model.refusals(verdict, 'hard', 'risk', 'soft'):
            level, title, text = model.ready_view(verdict)
            rows.append(action_row(title, verdict['line'] if verdict else text, LEVEL_ICONS.get(level), level))
        for refusal in model.refusals(verdict, 'hard', 'risk'):
            rows.append(action_row(refusal['text'], self.way(refusal), 'dialog-error-symbolic', 'error'))
        for warning in (verdict or {}).get('warnings', [])[:4]:
            rows.append(action_row(warning, None, 'dialog-information-symbolic', 'dim'))
        for row in rows:
            self.verdict_group.add(row)
        self.verdict_rows = rows
        self.verdict_group.set_visible(bool(rows))
        for row in self.soft_rows:
            self.soft_group.remove(row)
        self.soft_rows = []
        for refusal in model.refusals(verdict, 'soft'):
            row = plain(Adw.SwitchRow(), 'Install anyway: ' + refusal['text'], refusal['way'])
            row.set_active(self.accepted.get(refusal['code'], False))
            row.connect('notify::active', lambda r, _p, code=refusal['code']: self.accept(code, r.get_active()))
            self.soft_group.add(row)
            self.soft_rows.append(row)
        self.soft_group.set_visible(bool(self.soft_rows))
        for row in self.steps_rows:
            self.steps_group.remove(row)
        self.steps_rows = numbered((verdict or {}).get('manual_steps') or [])
        for row in self.steps_rows:
            self.steps_group.add(row)
        self.steps_group.set_visible(bool(self.steps_rows))
        self.update_state()

    def way(self, refusal):
        if self.input_id == 'auto' and model.detection_only(refusal):
            return 'If you know the game has an input this check missed, choose that input instead of Automatic.'
        return refusal['way']

    def accept(self, code, on):
        self.accepted[code] = on
        self.update_state()

    def build_providers(self):
        for row in self.provider_rows.values():
            self.provider_group.remove(row)
        self.provider_rows = {}
        chosen = getattr(self, 'chosen_provider', 'fsr4')
        first = None
        for provider in self.providers or [model.Provider('fsr4', 'FSR 4', 'AMD FSR 4, BC-250 build', detail='Built in')]:
            row = plain(Adw.ActionRow(), provider.label, provider.about if provider.ready else provider.about + ' · not prepared yet')
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            if first is None:
                first = check
            else:
                check.set_group(first)
            check.set_active(provider.id == chosen)
            check.connect('toggled', lambda c, pid=provider.id: c.get_active() and self.choose_provider(pid))
            row.add_prefix(check)
            row.set_activatable_widget(check)
            if not provider.ready:
                row.add_suffix(button('_Prepare…', self.window.show_upscalers, 'flat'))
            elif provider.id != 'fsr4':
                row.add_suffix(badge('Ready', 'success'))
            self.provider_group.add(row)
            self.provider_rows[provider.id] = row
        self.credit.set_visible(bool(self.ctx.helix_about) and any(p.id != 'fsr4' for p in self.providers or []))
        self.chosen_provider = chosen if chosen in self.provider_rows else 'fsr4'

    def providers_changed(self, providers):
        self.providers = providers
        self.build_providers()
        self.update_state()

    def choose_provider(self, provider):
        self.chosen_provider = provider
        self.update_state()

    def blocked(self):
        """Why Install cannot run yet, None when it can."""
        if self.checking:
            return 'Checking compatibility…'
        verdict = self.verdict
        hard = model.refusals(verdict, 'hard')
        if hard:
            return 'Not supported: ' + hard[0]['text']
        if model.refusals(verdict, 'risk'):
            return 'This game ships anti-cheat. Install despite anti-cheat is on the game’s page.'
        waiting = [r for r in model.refusals(verdict, 'soft') if not self.accepted.get(r['code'])]
        if waiting:
            return 'Accept each item under “Needs your OK” to install, or cancel.'
        provider = next((p for p in self.providers or [] if p.id == self.chosen_provider), None)
        if provider is not None and not provider.ready:
            return provider.label + ' is not prepared on this computer yet: choose Prepare… or another upscaler.'
        return None

    def update_state(self):
        reason = self.blocked()
        self.install_button.set_sensitive(reason is None)
        self.hint.set_text(reason or ('Setup checks again that the game and its launcher are closed, then installs.'))

    def choice(self):
        accept = [r['code'] for r in model.refusals(self.verdict, 'soft') if self.accepted.get(r['code'])]
        return model.InstallChoice(self.input_id, self.chosen_provider, [], accept, self.risk_sentence)

    def install(self):
        if self.blocked() is not None:
            return
        self.install_button.set_sensitive(False)
        self.window.reader.call(self.ctx.blockers, self.ctx.installer, [self.game.exe], True, done=self.closed_check,
                                failed=lambda error: self.closed_check([]))

    def closed_check(self, names):
        self.update_state()
        if names:
            self.banner.set_title('Close ' + model.joined(names) + ' first. A running launcher can overwrite the launch '
                                  'settings Setup writes.')
            self.banner.set_revealed(True)
            return
        self.banner.set_revealed(False)
        steps = list((self.verdict or {}).get('manual_steps') or [])
        choice, game, window = self.choice(), self.game, self.window
        self.close()
        window.run(f'Installing {window.ctx.name}', [Step(game.title, model.install_args(game.exe, choice), game)],
                   working=f'Installing {window.ctx.name} into {game.title}',
                   success=f'{window.ctx.name} is installed in {game.title}',
                   next_steps=steps + ['Reopen your launcher and play normally.'])


# ------------------------------------------------------------------------------------------------- upscaler switch
class UpscalerDialog(Adw.Dialog):
    """Switch an installed game to another upscaler (install.py configure --upscaler)."""

    def __init__(self, window, game):
        super().__init__(title='Upscaler', content_width=560, content_height=460)
        self.window, self.game = window, game
        current = ((game.record or {}).get('upscaler') or {}).get('name') or 'fsr4'
        self.current = 'hlx-dlss' if current == 'helixsr' and any(p.id == 'hlx-dlss' for p in window.providers or []) \
            else current
        self.chosen = self.current
        view = Adw.ToolbarView()
        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        header.pack_start(button('_Cancel', self.close))
        self.switch_button = button('_Switch', self.switch, 'suggested-action')
        header.pack_end(self.switch_button)
        header.set_title_widget(Adw.WindowTitle(title='Upscaler', subtitle=game.title))
        view.add_top_bar(header)
        page = Adw.PreferencesPage()
        self.group = group(None, 'Frame generation stays XeFG with every upscaler. A switch can be undone with Roll '
                                 'Back. Close the game first.')
        page.add(self.group)
        if window.ctx.helix_about:
            credit = group()
            credit.add(text_label(window.ctx.helix_about, ['dim-label', 'caption'], wrap=True))
            page.add(credit)
        view.set_content(page)
        self.set_child(view)
        self.rows = []
        self.build()
        window.providers_listeners.append(self.providers_changed)
        self.connect('closed', lambda *_: window.providers_listeners.remove(self.providers_changed))

    def build(self):
        for row in self.rows:
            self.group.remove(row)
        self.rows, first = [], None
        if self.window.providers is None:
            waiting = action_row('Checking the prepared upscalers…')
            waiting.add_suffix(spinner())
            self.group.add(waiting)
            self.rows.append(waiting)
        for provider in self.window.providers or []:
            row = plain(Adw.ActionRow(), provider.label, provider.about if provider.ready else provider.detail)
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            if first is None:
                first = check
            else:
                check.set_group(first)
            check.set_active(provider.id == self.chosen)
            check.connect('toggled', lambda c, pid=provider.id: c.get_active() and self.choose(pid))
            row.add_prefix(check)
            row.set_activatable_widget(check)
            if provider.id == self.current:
                row.add_suffix(badge('Current', 'accent'))
            elif not provider.ready:
                row.add_suffix(button('_Prepare…', self.window.show_upscalers, 'flat'))
            self.group.add(row)
            self.rows.append(row)
        self.update_state()

    def providers_changed(self, providers):
        self.build()

    def choose(self, provider):
        self.chosen = provider
        self.update_state()

    def update_state(self):
        # An upscaler that is not prepared yet cannot be switched to: its row offers Prepare… instead.
        provider = next((p for p in self.window.providers or [] if p.id == self.chosen), None)
        self.switch_button.set_sensitive(self.chosen != self.current and provider is not None and provider.ready)

    def switch(self):
        provider = next(p for p in self.window.providers if p.id == self.chosen)
        game, window = self.game, self.window
        self.close()
        window.when_closed([game], False, lambda: window.run(
            'Switching Upscaler', [Step(game.title, ['configure', str(game.exe), '--upscaler', provider.id], game)],
            working=f'Switching {game.title} to {provider.label}', success=f'{game.title} now uses {provider.label}'))


# ------------------------------------------------------------------------------------------------- update review
class UpdateDialog(Adw.Dialog):
    """The update plan for every game, grouped by outcome, before one confirmation: what changes where, which games are
    up to date, pinned, running or need attention, and why. Update runs only the games that have something to update."""

    def __init__(self, window, games, title='Update All Games', refresh=False, scope=True):
        super().__init__(title=title, content_width=700, content_height=720)
        self.window, self.games, self.refresh = window, games, refresh
        self.component, self.items, self.generation = 'all', [], 0
        view = Adw.ToolbarView()
        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        header.pack_start(button('_Cancel', self.close))
        self.update_button = button('_Update', self.update, 'suggested-action')
        self.update_button.set_sensitive(False)
        header.pack_end(self.update_button)
        header.set_title_widget(Adw.WindowTitle(title=title, subtitle=window.ctx.name + ' ' + window.ctx.version))
        view.add_top_bar(header)
        if scope:
            switcher = Gtk.Box(halign=Gtk.Align.CENTER, margin_top=8, margin_bottom=8)
            switcher.add_css_class('linked')
            everything = Gtk.ToggleButton(label='Everything', active=True)
            upscalers = Gtk.ToggleButton(label='Upscalers only', group=everything)
            everything.connect('toggled', lambda b: b.get_active() and self.set_component('all'))
            upscalers.connect('toggled', lambda b: b.get_active() and self.set_component('upscaler'))
            switcher.append(everything)
            switcher.append(upscalers)
            view.add_top_bar(switcher)
        self.stack = Gtk.Stack()
        loading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.CENTER)
        loading.append(Gtk.Spinner(spinning=True, width_request=32, height_request=32))
        self.loading_label = text_label('', ['dim-label'], xalign=0.5)
        loading.append(self.loading_label)
        self.stack.add_named(loading, 'loading')
        self.page = None
        view.set_content(self.stack)
        note = bar_text('Settings, launch options and original backups are kept. ' +
                        ('The game’s page can roll the refresh back.' if refresh else
                         'Each game’s page can roll its update back.'), ['dim-label', 'caption'])
        note_box = Gtk.Box(margin_top=8, margin_bottom=10, margin_start=16, margin_end=16)
        note_box.append(note)
        view.add_bottom_bar(note_box)
        self.set_child(view)
        self.plan()

    def set_component(self, component):
        if component != self.component:
            self.component = component
            self.plan()

    def plan(self):
        self.generation += 1
        generation = self.generation
        self.update_button.set_sensitive(False)
        self.stack.set_visible_child_name('loading')
        self.loading_label.set_text(f'Checking {len(self.games)} game{"s" if len(self.games) != 1 else ""}…')
        ctx, games, component, refresh = self.window.ctx, list(self.games), self.component, self.refresh

        def work():
            return [model.plan_game(ctx, game, component, refresh) for game in games]
        self.window.reader.call(work, done=lambda items: self.show(generation, items))

    def show(self, generation, items):
        if generation != self.generation:
            return
        self.items = items
        if self.page is not None:
            self.stack.remove(self.page)
        self.page = Adw.PreferencesPage()
        ctx = self.window.ctx
        for key, title, _ in model.UPDATE_GROUPS:
            members = [item for item in items if item.group == key]
            if not members:
                continue
            suffix = button('Check _Again', self.plan, 'flat') if key == 'running' else None
            # A recipe refresh the installer declines (no qualified refresh for the game) is information, not trouble.
            declined = self.refresh and key == 'attention' and all(item.status == 'blocked' for item in members)
            section = group(f'{"Not refreshed" if declined else title} ({len(members)})', suffix=suffix)
            for item in members:
                level = {'update': 'accent', 'running': 'warning', 'attention': 'dim' if declined else 'warning',
                         'pinned': 'dim', 'current': 'success'}[key]
                icon_name = {'update': 'software-update-available-symbolic', 'running': 'media-playback-start-symbolic',
                             'attention': 'dialog-information-symbolic' if declined else 'dialog-warning-symbolic',
                             'pinned': 'changes-prevent-symbolic', 'current': 'emblem-ok-symbolic'}[key]
                if item.changes or item.notes:
                    row = plain(Adw.ExpanderRow(), item.title, model.plan_reason(item, ctx))
                    row.add_prefix(icon(icon_name, level))
                    for change, details in item.changes:
                        row.add_row(plain(Adw.ActionRow(), change, '\n'.join(details) if details else None))
                    for note in item.notes:
                        row.add_row(action_row(note, None, 'dialog-information-symbolic', 'dim'))
                else:
                    row = action_row(item.title, model.plan_reason(item, ctx), icon_name, level)
                section.add(row)
            self.page.add(section)
        self.stack.add_named(self.page, 'review')
        self.stack.set_visible_child_name('review')
        count = sum(1 for item in items if item.status == 'update')
        self.update_button.set_sensitive(count > 0)
        if self.refresh:
            self.update_button.set_label('_Apply Recipe' if count else 'Nothing to Refresh')
        else:
            self.update_button.set_label(f'_Update {count} Game{"s" if count != 1 else ""}' if count else 'Nothing to Update')

    def update(self):
        games = {game.key: game for game in self.games}
        steps = [Step(item.title, model.update_args(item.exe, self.component, self.refresh), games.get(str(item.exe)))
                 for item in self.items if item.status == 'update']
        if not steps:
            return
        window, many = self.window, len(steps) > 1
        self.close()
        if self.refresh:
            window.run('Refreshing Recipe', steps, working=f'Applying the latest recipe to {steps[0].title}',
                       success=f'{steps[0].title} has the latest recipe')
            return
        window.run('Updating', steps, working=f'Updating {len(steps)} games' if many else f'Updating {steps[0].title}',
                   success=f'{len(steps)} games updated' if many else f'{steps[0].title} is updated')


# ------------------------------------------------------------------------------------------------- upscalers and HLX
class UpscalersDialog(Adw.Dialog):
    """The upscalers this package installs and whether each is ready on this computer; HLX is prepared here once for
    every game (or found in a folder prepared before)."""

    def __init__(self, window):
        super().__init__(title='Upscalers', content_width=620, content_height=640)
        self.window = window
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        self.stack = Gtk.Stack()
        loading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.CENTER)
        loading.append(Gtk.Spinner(spinning=True, width_request=32, height_request=32))
        loading.append(text_label('Checking the prepared upscalers…', ['dim-label'], xalign=0.5))
        self.stack.add_named(loading, 'loading')
        self.page = None
        view.set_content(self.stack)
        self.set_child(view)
        window.providers_listeners.append(self.show)
        self.connect('closed', lambda *_: window.providers_listeners.remove(self.show))
        if window.providers is not None:
            self.show(window.providers)
        window.check_providers()

    def show(self, providers):
        if self.page is not None:
            self.stack.remove(self.page)
        page = self.page = Adw.PreferencesPage()
        listing = group('Upscalers', 'Frame generation is XeFG with each of them. Each game’s page switches its upscaler.')
        for provider in providers:
            row = action_row(provider.label, provider.detail if not provider.ready or provider.id == 'fsr4' else
                             provider.detail + (' · ' + provider.folder if provider.folder else ''),
                             'emblem-ok-symbolic' if provider.ready else 'dialog-warning-symbolic',
                             'success' if provider.ready else 'warning')
            row.add_suffix(badge('Ready', 'success') if provider.ready else badge('Not prepared', 'warning'))
            listing.add(row)
        page.add(listing)
        if model.hlx_catalog(self.window.ctx):
            hlx = group('HLX', 'Prepared once for every game. Built model files stay on this computer.')
            prepare = action_row('Prepare HLX', 'Build HLX DLSS and HLX FSR 4 from your local NVIDIA and AMD model '
                                 'inputs. Takes several minutes; no game is changed.')
            prepare.add_suffix(button('_Prepare…', lambda: PrepareDialog(self.window).present(self.window), 'suggested-action'
                                      if not all(p.ready for p in providers) else 'flat'))
            hlx.add(prepare)
            folder = action_row('Use a prepared folder', 'Choose an official HelixSR release folder already prepared on '
                                'this computer.')
            folder.add_suffix(button('_Choose…', self.choose_folder, 'flat'))
            hlx.add(folder)
            page.add(hlx)
        elif any(p.id == 'helixsr' for p in providers):
            helix = next(p for p in providers if p.id == 'helixsr')
            legacy = group('HelixSR')
            if helix.state in ('missing', 'unknown'):
                row = action_row('Download HelixSR', 'The official release from its GitHub releases, complete and '
                                 'unmodified, checked by SHA-256. Then build it once with HelixSR’s own setup.')
                row.add_suffix(button('_Download…', self.download_helixsr, 'suggested-action'))
                legacy.add(row)
            elif helix.state == 'unbuilt':
                row = action_row('Build HelixSR once', 'Run HelixSR’s own setup to prepare the downloaded release.')
                row.add_suffix(button('_Show How…', lambda: TextDialog(self.window, 'Build HelixSR', ['helixsr'])
                                      .present(self.window), 'flat'))
                legacy.add(row)
            page.add(legacy)
        if self.window.ctx.helix_about:
            credit = group()
            credit.add(text_label(self.window.ctx.helix_about, ['dim-label', 'caption'], wrap=True))
            page.add(credit)
        self.stack.add_named(page, 'page')
        self.stack.set_visible_child_name('page')

    def choose_folder(self):
        dialog = Gtk.FileDialog(title='Prepared HelixSR release folder')

        def chosen(dialog, result):
            try:
                folder = dialog.select_folder_finish(result)
            except GLib.Error:
                return
            if folder is not None and folder.get_path():
                self.window.run('Checking Prepared Folder', [Step('HLX', ['helixsr', '--helixsr', folder.get_path()])],
                                working='Checking the prepared folder', success='HLX is ready for every game',
                                on_finished=lambda _: self.window.check_providers())
        dialog.select_folder(self.window, None, chosen)

    def download_helixsr(self):
        alert = Adw.AlertDialog(heading='Download HelixSR?', body=(self.window.ctx.helix_about or 'HelixSR') + '\n\nSetup '
                                'downloads the official release from its GitHub releases, complete and unmodified, checked '
                                'by SHA-256. HelixSR’s own setup then builds it once and asks you before it downloads '
                                'NVIDIA’s DLSS DLL.')
        alert.add_response('cancel', '_Cancel')
        alert.add_response('download', '_Download')
        alert.set_response_appearance('download', Adw.ResponseAppearance.SUGGESTED)
        alert.set_default_response('cancel')
        alert.set_close_response('cancel')

        def answered(_alert, response):
            if response == 'download':
                self.window.run('Downloading HelixSR', [Step('HelixSR', ['helixsr'])],
                                working='Downloading HelixSR from github.com/lonewolf0622/HelixSR',
                                success='HelixSR is downloaded', on_finished=lambda _: self.window.check_providers())
        alert.connect('response', answered)
        alert.present(self.window)


class PrepareDialog(Adw.Dialog):
    """Prepare HLX: the two local model inputs and what the build needs, then install.py hlx."""

    def __init__(self, window):
        super().__init__(title='Prepare HLX', content_width=600, content_height=600)
        self.window = window
        self.inputs = {'dlss': None, 'amd': None}
        view = Adw.ToolbarView()
        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        header.pack_start(button('_Cancel', self.close))
        self.prepare_button = button('_Prepare', self.prepare, 'suggested-action')
        self.prepare_button.set_sensitive(False)
        header.pack_end(self.prepare_button)
        view.add_top_bar(header)
        page = Adw.PreferencesPage()
        files = group('Model inputs', 'Your own local copies, identified in dependencies.json. Setup checks them by '
                                      'SHA-256 and never uploads them.')
        self.rows = {}
        for key, title, name in (('dlss', 'NVIDIA DLSS model input', 'nvngx_dlss.dll'),
                                 ('amd', 'AMD model input', 'amdxcffx64.dll')):
            row = action_row(title, name + ' · not chosen')
            row.add_suffix(button('_Choose…', lambda k=key, n=name: self.choose(k, n), 'flat'))
            files.add(row)
            self.rows[key] = (row, name)
        page.add(files)
        self.needs = group('Needed for the build', 'Preparation downloads the complete official archive and Microsoft’s '
                                                   'shader compilers, checks their hashes, and builds with networking off.')
        self.needs_rows = []
        page.add(self.needs)
        view.set_content(page)
        self.set_child(view)
        window.reader.call(model.hlx_requirements, done=self.requirements, probe=True,
                           failed=lambda error: self.needs.add(action_row('Setup could not check what the build needs',
                                                                          str(error), 'dialog-error-symbolic', 'error')))

    def requirements(self, found):
        self.missing = [what for what, present, _ in found if not present]
        for what, present, how in found:
            row = action_row(what, 'Installed' if present else how, 'emblem-ok-symbolic' if present else 'dialog-error-symbolic',
                             'success' if present else 'error')
            self.needs.add(row)
        self.update_state()

    def choose(self, key, name):
        dialog = Gtk.FileDialog(title=name)

        def chosen(dialog, result):
            try:
                file = dialog.open_finish(result)
            except GLib.Error:
                return
            if file is not None and file.get_path():
                self.inputs[key] = file.get_path()
                row, label = self.rows[key]
                row.set_subtitle(file.get_path())
                self.update_state()
        dialog.open(self.window, None, chosen)

    def update_state(self):
        self.prepare_button.set_sensitive(all(self.inputs.values()) and not getattr(self, 'missing', ['?']))

    def prepare(self):
        window, inputs = self.window, dict(self.inputs)
        self.close()
        window.run('Preparing HLX', [Step('HLX', ['hlx', '--dlss-input', inputs['dlss'], '--amd-input', inputs['amd']])],
                   working='Preparing HLX for every game. This takes several minutes.',
                   success='HLX is prepared for every game', on_finished=lambda _: window.check_providers())


# ------------------------------------------------------------------------------------------------- system check
class SystemDialog(Adw.Dialog):
    """doctor's checks as a summary and one row each: what the BC-250 experience depends on outside the game folders."""

    def __init__(self, window):
        super().__init__(title='System Check', content_width=640, content_height=680)
        self.window = window
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.pack_start(button('', self.copy, 'flat', icon_name='edit-copy-symbolic', tooltip='Copy'))
        header.pack_start(button('', self.rerun, 'flat', icon_name='view-refresh-symbolic', tooltip='Check Again'))
        view.add_top_bar(header)
        self.stack = Gtk.Stack()
        loading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.CENTER)
        loading.append(Gtk.Spinner(spinning=True, width_request=32, height_request=32))
        loading.append(text_label('Checking this system…', ['dim-label'], xalign=0.5))
        self.stack.add_named(loading, 'loading')
        self.page = None
        view.set_content(self.stack)
        self.set_child(view)
        window.system_listeners.append(self.show)
        self.connect('closed', lambda *_: window.system_listeners.remove(self.show))
        if window.system is not None:
            self.show(window.system)
        else:
            window.check_system()

    def rerun(self):
        self.stack.set_visible_child_name('loading')
        self.window.check_system()

    def show(self, rows):
        if self.page is not None:
            self.stack.remove(self.page)
        level, title, description = model.system_summary(rows, self.window.ctx.name)
        self.page = Adw.PreferencesPage()
        top = group()
        gpu = next((text for check_level, item, text in rows if item == 'GPU' and check_level == 'OK'), None)
        top.add(hero(gpu or 'This computer', level, title, description))
        self.page.add(top)
        # Warnings first: what to act on; then what passed; then what describes this system.
        for levels, name, note in ((('WARN',), 'Needs attention', None), (('OK',), 'Passed', None),
                                   (('INFO',), 'About this system', 'Nothing is changed by this check.')):
            members = [row for row in rows if row[0] in levels]
            if not members:
                continue
            section = group(name, note)
            for check_level, item, text in members:
                mapped = DOCTOR_LEVELS.get(check_level, 'neutral')
                section.add(action_row(item, text, LEVEL_ICONS[mapped], mapped if mapped != 'neutral' else 'dim'))
            self.page.add(section)
        self.stack.add_named(self.page, 'page')
        self.stack.set_visible_child_name('page')

    def copy(self):
        rows = self.window.system or []
        copy_text(self, '\n'.join(f'{level:4}  {item}: {text}' for level, item, text in rows) + '\n')
        self.window.toast('System check copied')


# ------------------------------------------------------------------------------------------------- add a game
class BrowseDialog(Adw.Dialog):
    """Add a game from the installed Steam and Heroic games: Setup finds its rendering executable (gamescan) and the
    player confirms it or picks another."""

    def __init__(self, window):
        super().__init__(title='Add a Game', content_width=620, content_height=700)
        self.window, self.games, self.scan, self.generation = window, [], None, 0
        self.nav = Adw.NavigationView()
        self.nav.add(self.list_page())
        self.set_child(self.nav)
        window.reader.call(model.installed_games, window.ctx.home, done=self.listed,
                           failed=lambda error: self.listed([]))

    def list_page(self):
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        footer = Gtk.Box(halign=Gtk.Align.CENTER, margin_top=6, margin_bottom=8)
        footer.append(text_label('Not listed?', ['dim-label']))
        footer.append(button('_Choose its executable…', self.choose_file, 'flat'))
        view.add_bottom_bar(footer)
        search = Gtk.SearchEntry(placeholder_text='Search installed games', margin_start=12, margin_end=12, margin_bottom=8)
        search.connect('search-changed', lambda e: self.listing.invalidate_filter())
        self.search = search
        view.add_top_bar(search)
        self.stack = Gtk.Stack()
        loading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.CENTER)
        loading.append(Gtk.Spinner(spinning=True, width_request=32, height_request=32))
        loading.append(text_label('Looking for installed Steam and Heroic games…', ['dim-label'], xalign=0.5))
        self.stack.add_named(loading, 'loading')
        self.listing = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, margin_start=12, margin_end=12, margin_bottom=12,
                                   valign=Gtk.Align.START)
        self.listing.add_css_class('boxed-list')
        self.listing.set_filter_func(self.matches)
        self.listing.connect('row-activated', lambda _l, row: self.pick(row.game))
        self.stack.add_named(Gtk.ScrolledWindow(child=self.listing, vexpand=True), 'list')
        empty = Adw.StatusPage(icon_name='applications-games-symbolic', title='No installed games found',
                               description=esc('Choose the game’s executable instead.'))
        empty.set_child(button('_Choose Executable…', self.choose_file, 'pill', 'suggested-action', icon_name=None))
        self.stack.add_named(empty, 'empty')
        view.set_content(self.stack)
        return Adw.NavigationPage(child=view, title='Add a Game', tag='list')

    def matches(self, row):
        query = self.search.get_text().casefold().strip()
        return not query or query in row.game['name'].casefold()

    def listed(self, games):
        known = {model.same_path(game.exe.parent) for game in self.window.games}
        self.games = sorted(games, key=lambda g: str(g.get('name')).casefold())
        for game in self.games:
            row = plain(Adw.ActionRow(activatable=True), game.get('name') or Path(game['path']).name,
                        {'steam': 'Steam', 'gog': 'GOG (Heroic)', 'epic': 'Epic (Heroic)'}.get(game.get('store'),
                                                                                           str(game.get('store') or '')))
            row.game = dict(game, name=str(game.get('name') or Path(game['path']).name))
            folder = model.same_path(game['path'])
            if any(path == folder or path.startswith(folder.rstrip(os.sep) + os.sep) for path in known):
                row.add_suffix(badge('In library', 'dim'))
            row.add_suffix(icon('go-next-symbolic', 'dim'))
            self.listing.append(row)
        self.stack.set_visible_child_name('list' if self.games else 'empty')

    def pick(self, game):
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        stack = Gtk.Stack()
        loading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.CENTER)
        loading.append(Gtk.Spinner(spinning=True, width_request=32, height_request=32))
        loading.append(text_label('Finding the game’s rendering executable…', ['dim-label'], xalign=0.5))
        stack.add_named(loading, 'loading')
        view.set_content(stack)
        page = Adw.NavigationPage(child=view, title=game['name'], tag='game')
        self.nav.push(page)
        self.generation += 1
        generation = self.generation
        self.window.reader.call(model.find_executable, game, self.window.ctx.home,
                                done=lambda found: self.found(generation, stack, game, found),
                                failed=lambda error: self.found(generation, stack, game, dict(error=str(error))))

    def found(self, generation, stack, game, found):
        if generation != self.generation:
            return
        page = Adw.PreferencesPage()
        candidates = found.get('candidates') or []
        if found.get('error') or not candidates:
            status = Adw.StatusPage(icon_name='dialog-warning-symbolic', title='No Windows executable found',
                                    description=esc(found.get('error') or 'Choose the game’s executable yourself.'))
            status.set_child(button('_Choose Executable…', self.choose_file, 'pill'))
            stack.add_named(status, 'page')
            stack.set_visible_child_name('page')
            return
        choose = group('Executable', 'Setup picked the one that renders the game. Unreal Engine games often render from '
                                     'Binaries/Win64, not the launcher in the game folder.')
        self.exe_row = plain(Adw.ComboRow(), 'Rendering executable')
        self.exe_row.set_model(Gtk.StringList.new(candidates))
        self.exe_row.set_selected(0)
        choose.add(self.exe_row)
        page.add(choose)
        add = Gtk.Box(halign=Gtk.Align.CENTER, margin_top=12)
        add.append(button('_Add to Library', lambda: self.add(Path(game['path']) / candidates[self.exe_row.get_selected()]),
                          'pill', 'suggested-action'))
        holder = group()
        holder.add(add)
        page.add(holder)
        stack.add_named(page, 'page')
        stack.set_visible_child_name('page')

    def add(self, exe):
        window = self.window
        self.close()
        window.add_games([exe])

    def choose_file(self):
        window = self.window
        self.close()
        window.choose_executables()


# ------------------------------------------------------------------------------------------------- the library list
class GameRow(Gtk.ListBoxRow):
    def __init__(self, game, ctx):
        super().__init__()
        self.game = game
        self.section = model.section(game, ctx)
        box = Gtk.Box(spacing=12, margin_top=7, margin_bottom=7, margin_start=4, margin_end=4)
        name, level = STATE_ICONS[model.state(game, ctx)]
        box.append(icon(name, level))
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1, hexpand=True)
        texts.append(text_label(game.title, ellipsize=True))
        texts.append(text_label(model.subtitle(game, ctx), ['caption', 'dim-label'], ellipsize=True))
        box.append(texts)
        mark = model.badge(game, ctx)
        if mark:
            box.append(badge(*mark))
        elif model.state(game, ctx) == 'available' and not game.checked:
            box.append(spinner())
        self.set_child(box)
        self.set_tooltip_text(str(game.exe))


# ------------------------------------------------------------------------------------------------- the window
class Window(Adw.ApplicationWindow):
    def __init__(self, app, ctx):
        super().__init__(application=app, title=ctx.name)
        self.ctx = ctx
        self.reader = Reader()
        self.games, self.added, self.notes = [], [], []
        self.verdicts, self.integrity, self.titles = {}, {}, None
        self.providers, self.system = None, None
        self.providers_listeners, self.system_listeners = [], []
        self.selected_key, self.selecting, self.loaded = None, False, False
        self.operations = 0
        self.set_default_size(1180, 780)
        self.set_size_request(360, 480)
        self.toasts = Adw.ToastOverlay()
        self.split = Adw.NavigationSplitView(min_sidebar_width=300, max_sidebar_width=400, sidebar_width_fraction=0.32)
        self.split.set_sidebar(self.sidebar())
        self.toasts.set_child(self.split)
        self.set_content(self.toasts)
        breakpoint_ = Adw.Breakpoint.new(Adw.BreakpointCondition.parse('max-width: 760sp'))
        breakpoint_.add_setter(self.split, 'collapsed', True)
        self.add_breakpoint(breakpoint_)
        self.connect('close-request', self.closing)
        for name, callback in (('add-exe', self.choose_executables), ('browse', self.browse), ('update-all', self.update_all),
                               ('upscalers', self.show_upscalers), ('system', self.show_system), ('refresh', self.reload),
                               ('search', lambda: self.search.grab_focus()), ('about', self.about)):
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', lambda *_a, c=callback: c())
            self.add_action(action)
        if ctx.installer is None:
            # Without its installer Setup can change nothing: say so, and leave the command line as the way on.
            self.split.set_content(self.broken_page())
            self.list_stack.set_visible_child_name('empty')
            self.system_icon.set_visible_child_name('done')
            self.system_image.set_from_icon_name('action-unavailable-symbolic')
            self.system_label.set_text('Unavailable')
            for name in ('add-exe', 'browse', 'update-all', 'upscalers', 'system', 'refresh'):
                self.lookup_action(name).set_enabled(False)
            return
        self.split.set_content(self.overview_page())
        self.refresh()
        self.check_system()
        self.check_providers()

    # ---------------------------------------------------------------- sidebar
    def sidebar(self):
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        add_menu = Gio.Menu()
        add_menu.append('Choose from Steam and Heroic…', 'win.browse')
        add_menu.append('Choose a Game Executable…', 'win.add-exe')
        header.pack_start(Gtk.MenuButton(icon_name='list-add-symbolic', menu_model=add_menu, tooltip_text='Add a Game'))
        menu = Gio.Menu()
        actions = Gio.Menu()
        actions.append('Update All Games…', 'win.update-all')
        actions.append('Upscalers…', 'win.upscalers')
        actions.append('System Check', 'win.system')
        menu.append_section(None, actions)
        other = Gio.Menu()
        other.append('Refresh', 'win.refresh')
        other.append('About ' + self.ctx.name, 'win.about')
        menu.append_section(None, other)
        header.pack_end(Gtk.MenuButton(icon_name='open-menu-symbolic', menu_model=menu, primary=True, tooltip_text='Main Menu'))
        header.set_title_widget(Adw.WindowTitle(title=self.ctx.name, subtitle=self.ctx.version))
        view.add_top_bar(header)
        self.search = Gtk.SearchEntry(placeholder_text='Search games', margin_start=10, margin_end=10, margin_bottom=6)
        self.search.connect('search-changed', lambda *_: (self.list.invalidate_filter(), self.list.invalidate_headers()))
        view.add_top_bar(self.search)
        self.banner = Adw.Banner(button_label='_Review', revealed=False)
        self.banner.connect('button-clicked', lambda *_: self.update_all())
        view.add_top_bar(self.banner)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.list.add_css_class('navigation-sidebar')
        self.list.set_header_func(self.header)
        self.list.set_filter_func(self.matches)
        self.list.connect('row-selected', self.row_selected)
        self.list.connect('row-activated', lambda *_: self.split.set_show_content(True))
        self.list_stack = Gtk.Stack()
        loading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, valign=Gtk.Align.CENTER)
        loading.append(Gtk.Spinner(spinning=True, width_request=28, height_request=28))
        loading.append(text_label('Reading your library…', ['dim-label'], xalign=0.5))
        self.list_stack.add_named(loading, 'loading')
        self.list_stack.add_named(Gtk.ScrolledWindow(child=self.list, vexpand=True,
                                                     hscrollbar_policy=Gtk.PolicyType.NEVER), 'list')
        empty = Adw.StatusPage(icon_name='applications-games-symbolic', title='No games yet',
                               description=esc('Games that already have ' + self.ctx.name + ' appear here by themselves.'))
        empty.add_css_class('compact')
        self.list_stack.add_named(empty, 'empty')
        view.set_content(self.list_stack)
        self.system_button = Gtk.Button()
        self.system_button.add_css_class('flat')
        self.system_button.connect('clicked', lambda *_: self.show_system())
        footer = Gtk.Box(spacing=10, margin_start=4, margin_end=4)
        self.system_icon = Gtk.Stack()
        self.system_icon.add_named(Gtk.Spinner(spinning=True), 'busy')
        self.system_image = Gtk.Image()
        self.system_icon.add_named(self.system_image, 'done')
        footer.append(self.system_icon)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        labels.append(text_label('System check', ['caption-heading']))
        self.system_label = text_label('Checking…', ['caption', 'dim-label'], ellipsize=True)
        labels.append(self.system_label)
        footer.append(labels)
        footer.append(icon('go-next-symbolic', 'dim'))
        self.system_button.set_child(footer)
        bottom = Gtk.Box(margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        self.system_button.set_hexpand(True)
        bottom.append(self.system_button)
        view.add_bottom_bar(bottom)
        return Adw.NavigationPage(child=view, title=self.ctx.name, tag='library')

    def header(self, row, before):
        if before is None or before.section != row.section:
            title = next(title for key, title, _ in model.SECTIONS if key == row.section)
            row.set_header(text_label(title.upper(), ['sidebar-section']))
        else:
            row.set_header(None)

    def matches(self, row):
        query = self.search.get_text().casefold().strip()
        return not query or query in row.game.title.casefold() or query in row.game.exe.name.casefold()

    def row_selected(self, _list, row):
        if self.selecting:
            return
        if row is None:
            return
        self.selected_key = row.game.key
        self.show_game(row.game)

    # ---------------------------------------------------------------- library
    def refresh(self, select=None):
        if self.ctx.installer is None:
            return
        if select is not None:
            self.selected_key = select
        if not self.loaded:
            self.list_stack.set_visible_child_name('loading')
        ctx, added, titles = self.ctx, list(self.added), self.titles

        def read():
            # Launcher titles once per session (Steam's appinfo cache can be large); Refresh reads them again.
            found = titles if titles is not None else model.launcher_titles(ctx.home)
            return (*model.load_library(ctx, added, found), found)
        self.reader.call(read, done=self.loaded_library, failed=self.library_failed)

    def reload(self):
        """Refresh: read everything again, also what Setup keeps between refreshes (titles, checks, upscalers)."""
        self.titles = None
        self.verdicts.clear()
        self.integrity.clear()
        self.refresh()
        self.check_providers()

    def library_failed(self, error):
        self.loaded_library(([], ['Setup could not read the library: ' + str(error)], self.titles))

    def loaded_library(self, result):
        games, self.notes, self.titles = result
        self.loaded = True
        for game in games:
            if game.key in self.verdicts:
                game.verdict, game.checked = self.verdicts[game.key], True
            if game.key in self.integrity:
                game.integrity = self.integrity[game.key]
        self.games = games
        self.fill_list()
        updates = sum(1 for game in games if model.state(game, self.ctx) == 'update')
        self.banner.set_title(f'{updates} game{"s" if updates != 1 else ""} can be updated to {self.ctx.version}')
        self.banner.set_revealed(updates > 0)
        selected = self.game_by_key(self.selected_key)
        if selected is not None:
            self.show_game(selected)
        else:
            self.selected_key = None
            self.split.set_content(self.overview_page())
        for game in games:
            if model.state(game, self.ctx) == 'available' and not game.checked:
                self.check_game(game)

    def fill_list(self):
        self.selecting = True
        self.list.remove_all()
        selected = None
        for game in self.games:
            row = GameRow(game, self.ctx)
            self.list.append(row)
            if game.key == self.selected_key:
                selected = row
        if selected is not None:
            self.list.select_row(selected)
        self.selecting = False
        self.list_stack.set_visible_child_name('list' if self.games else 'empty')

    def game_by_key(self, key):
        if key is None:
            return None
        found = next((game for game in self.games if game.key == key), None)
        if found is None:
            # The same executable through another path (a symlinked library folder).
            same = model.same_path(key)
            found = next((game for game in self.games if model.same_path(game.exe) == same), None)
        return found

    def check_game(self, game):
        key = game.key
        self.reader.call(model.check_game, self.ctx, game.exe, done=lambda verdict: self.game_checked(key, verdict))

    def game_checked(self, key, verdict):
        self.verdicts[key] = verdict
        game = self.game_by_key(key)
        if game is None:
            return
        game.verdict, game.checked = verdict, True
        self.fill_list()
        if self.selected_key == key:
            self.show_game(game)

    def add_games(self, paths):
        for path in paths:
            path = Path(path).absolute()
            if all(model.same_path(path) != model.same_path(known) for known in self.added):
                self.added.append(path)
        if paths:
            self.refresh(select=str(Path(paths[0]).absolute()))

    def forget(self, game):
        self.added = [path for path in self.added if model.same_path(path) != model.same_path(game.exe)]
        self.verdicts.pop(game.key, None)
        self.selected_key = None
        self.refresh()

    def changed(self, games):
        """After an operation: what Setup knew about these games is stale."""
        for game in games:
            if game is None:
                continue
            self.verdicts.pop(game.key, None)
            self.integrity.pop(game.key, None)
            # A restored game leaves the library; it stays listed, so it can be installed again.
            if all(model.same_path(game.exe) != model.same_path(p) for p in self.added):
                self.added.append(game.exe)
        self.refresh()

    def check_system(self):
        self.system_icon.set_visible_child_name('busy')
        self.system_label.set_text('Checking…')
        self.reader.call(model.system_checks, self.ctx, done=self.system_checked, probe=True)

    def system_checked(self, rows):
        self.system = rows
        level, title, _ = model.system_summary(rows, self.ctx.name)
        self.system_image.set_from_icon_name(LEVEL_ICONS[level])
        for name in ('success', 'warning', 'error', 'accent', 'dim-label'):
            self.system_image.remove_css_class(name)
        tint(self.system_image, level)
        self.system_icon.set_visible_child_name('done')
        self.system_label.set_text('All checks passed' if level == 'success' else title)
        for listener in list(self.system_listeners):
            listener(rows)
        if self.selected_key is None and self.loaded:
            self.split.set_content(self.overview_page())

    def check_providers(self):
        self.reader.call(model.providers, self.ctx, done=self.providers_checked)

    def providers_checked(self, providers):
        self.providers = providers
        for listener in list(self.providers_listeners):
            listener(providers)

    # ---------------------------------------------------------------- pages
    def broken_page(self):
        status = Adw.StatusPage(icon_name='dialog-error-symbolic', title='Setup cannot load its installer',
                                description=esc((self.ctx.load_error or 'install.py did not load.') + '\n\nThe command '
                                                'line still works: see README.md beside Setup.'))
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        view.set_content(status)
        return Adw.NavigationPage(child=view, title=self.ctx.name, tag='broken')

    def overview_page(self):
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        installed = [g for g in self.games if g.installed]
        updates = [g for g in self.games if model.state(g, self.ctx) == 'update']
        attention = [g for g in self.games if model.section(g, self.ctx) == 'attention']
        if self.games:
            description = 'Frame generation for DirectX 12 games under Proton on the AMD BC-250. Choose a game to see ' \
                          'what it needs.'
        else:
            description = 'Frame generation for DirectX 12 games under Proton on the AMD BC-250. Add a game to install ' \
                          'it; games that already have ' + self.ctx.name + ' appear here by themselves.'
        status = Adw.StatusPage(icon_name='applications-games-symbolic', title=self.ctx.name + ' ' + self.ctx.version,
                                description=esc(description))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        clamp = Adw.Clamp(maximum_size=560, child=box)
        if self.loaded and self.games:
            listing = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
            listing.add_css_class('boxed-list')
            listing.append(action_row(f'{len(installed)} game{"s" if len(installed) != 1 else ""} with {self.ctx.name}',
                                      None, 'emblem-ok-symbolic', 'success' if installed else 'dim'))
            row = action_row(f'{len(updates)} update{"s" if len(updates) != 1 else ""} available' if updates else
                             'Every game is up to date', None, 'software-update-available-symbolic',
                             'accent' if updates else 'dim')
            row.add_suffix(button('_Review…' if updates else '_Check…', self.update_all, 'flat'))
            listing.append(row)
            if attention:
                listing.append(action_row(f'{len(attention)} game{"s" if len(attention) != 1 else ""} need attention',
                                          ', '.join(g.title for g in attention[:3]), 'dialog-warning-symbolic', 'warning'))
            if self.system is not None:
                level, title, _ = model.system_summary(self.system, self.ctx.name)
                row = action_row('System check: ' + ('all checks passed' if level == 'success' else title), None,
                                 LEVEL_ICONS[level], level)
                row.add_suffix(button('_Open…', self.show_system, 'flat'))
                listing.append(row)
            for note in self.notes:
                listing.append(action_row(note, None, 'dialog-warning-symbolic', 'warning'))
            box.append(listing)
        buttons = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        buttons.append(button('_Add a Game…', self.browse, 'pill', 'suggested-action'))
        if self.games:
            buttons.append(button('_Update All…', self.update_all, 'pill'))
        box.append(buttons)
        status.set_child(clamp)
        view.set_content(status)
        return Adw.NavigationPage(child=view, title=self.ctx.name, tag='overview')

    def show_game(self, game):
        page = GamePage(self, game)
        self.split.set_content(page)
        if game.installed and game.integrity is None and game.present:
            key = game.key
            self.reader.call(model.integrity, self.ctx, game, done=lambda found: self.integrity_checked(key, found))

    def integrity_checked(self, key, found):
        self.integrity[key] = found
        game = self.game_by_key(key)
        if game is not None:
            game.integrity = found
            if self.selected_key == key:
                content = self.split.get_content()
                if isinstance(content, GamePage) and content.game.key == key:
                    content.show_integrity(found)

    # ---------------------------------------------------------------- actions
    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=esc(text), timeout=4))

    def busy(self, on):
        self.operations += 1 if on else -1

    def closing(self, *_):
        if self.operations > 0:
            self.toast('Setup finishes the current step first.')
            return True
        return False

    def run(self, title, steps, working, success, next_steps=(), on_finished=None):
        """Run install.py steps in an operation dialog, then read the games they changed again."""
        def finished(results):
            self.changed([step.game for step in steps])
            if on_finished is not None:
                on_finished(results)
        OperationDialog(self, title, steps, working, success, next_steps, finished).start()

    def quietly(self, steps, success, game, failed_title):
        """A quick change (pin, track, settings): a toast when it worked, the installer's reason when it did not."""
        def done(results):
            self.busy(False)
            result = results[0]
            if result.ok:
                self.toast(success)
            else:
                alert = Adw.AlertDialog(heading=failed_title, body=model.failure_reason(result.lines))
                alert.add_response('close', '_Close')
                alert.present(self)
            self.changed([game])
        self.busy(True)
        Operation(self.ctx, steps, on_done=done).start()

    def when_closed(self, games, launchers, then):
        """then() once the games (and their launchers, for launcher edits) are closed; asks until they are or the player
        goes back."""
        def checked(names):
            if not names:
                then()
                return
            alert = Adw.AlertDialog(heading='Close ' + model.joined(names) + ' first',
                                    body='Setup changes the game’s files.' + (' A running launcher can overwrite the launch '
                                                                             'settings Setup writes.' if launchers else ''))
            alert.add_response('back', '_Back')
            alert.add_response('again', 'Check _Again')
            alert.set_response_appearance('again', Adw.ResponseAppearance.SUGGESTED)
            alert.set_default_response('again')
            alert.set_close_response('back')
            alert.connect('response', lambda _a, response: response == 'again' and self.when_closed(games, launchers, then))
            alert.present(self)
        self.reader.call(self.ctx.blockers, self.ctx.installer, [g.exe for g in games], launchers, done=checked,
                         failed=lambda error: checked([]))

    def confirm(self, heading, body, label, then, destructive=False):
        alert = Adw.AlertDialog(heading=heading, body=body)
        alert.add_response('cancel', '_Cancel')
        alert.add_response('go', label)
        alert.set_response_appearance('go', Adw.ResponseAppearance.DESTRUCTIVE if destructive else
                                      Adw.ResponseAppearance.SUGGESTED)
        alert.set_default_response('cancel')
        alert.set_close_response('cancel')
        alert.connect('response', lambda _a, response: response == 'go' and then())
        alert.present(self)

    def choose_executables(self):
        dialog = Gtk.FileDialog(title='Choose game executables')
        executables = Gtk.FileFilter(name='Windows games')
        for pattern in ('*.exe', '*.EXE'):
            executables.add_pattern(pattern)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(executables)
        dialog.set_filters(filters)
        start = model.steam_common(self.ctx.home)
        if start is not None:
            dialog.set_initial_folder(Gio.File.new_for_path(str(start)))

        def chosen(dialog, result):
            try:
                files = dialog.open_multiple_finish(result)
            except GLib.Error:
                return
            self.add_games([files.get_item(i).get_path() for i in range(files.get_n_items()) if files.get_item(i).get_path()])
        dialog.open_multiple(self, None, chosen)

    def browse(self):
        BrowseDialog(self).present(self)

    def update_all(self, games=None):
        candidates = games or [g for g in self.games if g.record and model.state(g, self.ctx) != 'available']
        if not candidates:
            alert = Adw.AlertDialog(heading='No game has ' + self.ctx.name + ' yet',
                                    body='Games that have it appear in the library by themselves. Add a game to install it.')
            alert.add_response('close', '_Close')
            alert.present(self)
            return
        UpdateDialog(self, candidates).present(self)

    def show_upscalers(self):
        UpscalersDialog(self).present(self)

    def show_system(self):
        SystemDialog(self).present(self)

    def about(self):
        dialog = Adw.AboutDialog(application_name=self.ctx.name, version=self.ctx.version,
                                 application_icon='applications-games-symbolic',
                                 comments='Frame generation for DirectX 12 games under Proton on the AMD BC-250.',
                                 license_type=Gtk.License.MIT_X11,
                                 website='https://github.com/daniel-h-0/freefg')
        if self.ctx.helix_about:
            dialog.add_legal_section('HelixSR (HLX)', None, Gtk.License.CUSTOM, self.ctx.helix_about)
        dialog.present(self)

    # per game
    def install(self, game):
        InstallDialog(self, game).present(self)

    def override(self, game):
        """Install despite anti-cheat, for this game only: the facts with Cancel as the default, then the sentence typed
        exactly, then Install with the override (install.py checks the sentence again)."""
        installer, refusal = self.ctx.installer, model.anticheat(game.verdict)
        names = list((refusal or {}).get('names') or ['anti-cheat'])
        first, *facts = installer.anticheat_warning(game.title, names, self.ctx.name).splitlines()
        alert = Adw.AlertDialog(heading='Install despite anti-cheat?', body=first)
        points = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for fact in facts:
            line = Gtk.Box(spacing=8)
            bullet = text_label('•', ['dim-label'])
            bullet.set_valign(Gtk.Align.START)
            line.append(bullet)
            text = text_label(fact, wrap=True)
            text.set_hexpand(True)
            line.append(text)
            points.append(line)
        points.append(text_label('Continue only if you accept that risk for this game.', ['heading'], wrap=True))
        alert.set_extra_child(points)
        alert.add_response('cancel', '_Cancel')
        alert.add_response('continue', 'C_ontinue…')
        alert.set_response_appearance('continue', Adw.ResponseAppearance.DESTRUCTIVE)
        alert.set_default_response('cancel')
        alert.set_close_response('cancel')
        alert.connect('response', lambda _a, response: response == 'continue' and self.sentence(game))
        alert.present(self)

    def sentence(self, game):
        installer = self.ctx.installer
        alert = Adw.AlertDialog(heading='Type the sentence',
                                body='To install ' + game.title + ' anyway, type this sentence exactly:\n\n' +
                                     installer.RISK_SENTENCE)
        entry = Gtk.Entry(activates_default=True, placeholder_text='Type the sentence above')
        alert.set_extra_child(entry)
        alert.add_response('cancel', '_Cancel')
        alert.add_response('override', '_Override for This Game')
        alert.set_response_appearance('override', Adw.ResponseAppearance.DESTRUCTIVE)
        alert.set_response_enabled('override', False)
        alert.set_default_response('cancel')
        alert.set_close_response('cancel')
        entry.connect('changed', lambda e: alert.set_response_enabled('override', installer.risk_confirmed(e.get_text())))
        alert.connect('response', lambda _a, response: response == 'override' and installer.risk_confirmed(entry.get_text())
                      and InstallDialog(self, game, entry.get_text().strip()).present(self))
        alert.present(self)

    def update_game(self, game, refresh=False):
        UpdateDialog(self, [game], title='Refresh Recipe' if refresh else 'Update ' + game.title, refresh=refresh,
                     scope=not refresh).present(self)

    def finish_update(self, game):
        self.when_closed([game], False, lambda: self.run(
            'Finishing Update', [Step(game.title, ['update', str(game.exe)], game)],
            working=f'Finishing the interrupted update of {game.title}', success=f'{game.title} is updated'))

    def rollback(self, game, interrupted=False):
        record = game.record or {}
        target = model.version((record.get('generations') or [{}])[-1].get('from')) if record.get('generations') else None
        heading = 'Undo the interrupted update?' if interrupted else f'Roll back to {target}?'
        body = ('The game returns to the release before the update.' if interrupted else
                f'{game.title} returns to {target}, the release before its last update or upscaler switch, byte for byte. '
                'Your settings are kept.')
        self.confirm(heading, body, '_Roll Back', lambda: self.when_closed([game], False, lambda: self.run(
            'Rolling Back', [Step(game.title, ['rollback', str(game.exe)], game)],
            working=f'Rolling back {game.title}', success=f'{game.title} is rolled back')))

    def restore(self, game):
        self.confirm(f'Restore the original files of {game.title}?',
                     f'This removes {self.ctx.name} from the game: its files, its launch settings and its private shader '
                     f'cache. The backup folder {getattr(self.ctx.installer, "STATE", "")} and its logs stay in the game '
                     'folder. You can install again later.', '_Restore',
                     lambda: self.when_closed([game], True, lambda: self.run(
                         'Restoring', [Step(game.title, ['restore', str(game.exe)], game)],
                         working=f'Restoring the original files of {game.title}',
                         success=f'{game.title} has its original files back',
                         next_steps=['Reopen your launcher and play normally.'])), destructive=True)

    def set_pin(self, game, on):
        release = model.version((game.record or {}).get('package'))
        self.quietly([Step(game.title, ['pin' if on else 'unpin', str(game.exe)], game)],
                     f'{game.title} stays on {release}' if on else f'{game.title} receives updates again', game,
                     'Pin did not change' if on else 'Unpin did not change')

    def track(self, game):
        self.quietly([Step(game.title, ['register', str(game.exe)], game)], f'Update All now includes {game.title}', game,
                     'Setup could not track this installation')

    def apply_settings(self, game, before, after):
        args = model.settings_args(before, after)
        if not args:
            return
        self.when_closed([game], False, lambda: self.quietly(
            [Step(game.title, ['configure', str(game.exe), *args], game)],
            'Settings saved. They apply the next time the game starts.', game, 'Settings were not saved'))

    def change_upscaler(self, game):
        UpscalerDialog(self, game).present(self)

    def status(self, game):
        TextDialog(self, 'Installation Details', ['status', str(game.exe)],
                   intro='Logs describe the last recorded session; they do not prove current frame generation or visual '
                         'correctness.').present(self)

    def report(self, game):
        TextDialog(self, 'Compatibility Report', ['check', '--report', str(game.exe)],
                   intro='What Install would do, or why it refuses, and a redacted report for a GitHub game report. '
                         'Nothing is changed.').present(self)

    def open_folder(self, game):
        launcher = Gtk.FileLauncher.new(Gio.File.new_for_path(str(game.exe)))

        def opened(launcher, result):
            try:
                launcher.open_containing_folder_finish(result)
            except GLib.Error as error:
                self.toast('The folder did not open: ' + error.message)
        launcher.open_containing_folder(self, None, opened)


# ------------------------------------------------------------------------------------------------- a game's page
class GamePage(Adw.NavigationPage):
    """One game: what matters now and its main action at the top, then its upscaler, settings, updates, recovery and
    diagnostics, each offered only where the game's state allows it."""

    def __init__(self, window, game):
        super().__init__(title=game.title, tag='game')
        self.window, self.game, self.ctx = window, game, window.ctx
        self.state = model.state(game, self.ctx)
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        menu = Gio.Menu()
        self.actions = Gio.SimpleActionGroup()
        for name, callback in (('folder', lambda: window.open_folder(game)), ('report', lambda: window.report(game)),
                               ('details', lambda: window.status(game)), ('forget', lambda: window.forget(game)),
                               ('copy-path', lambda: (copy_text(self, str(game.exe)), window.toast('Path copied')))):
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', lambda *_a, c=callback: c())
            self.actions.add_action(action)
        self.insert_action_group('game', self.actions)
        menu.append('Open Game Folder', 'game.folder')
        menu.append('Copy Executable Path', 'game.copy-path')
        menu.append('Compatibility Report…', 'game.report')
        if game.record:
            menu.append('Installation Details…', 'game.details')
        if game.added and self.state in ('available', 'unavailable'):
            menu.append('Remove from List', 'game.forget')
        header.pack_end(Gtk.MenuButton(icon_name='view-more-symbolic', menu_model=menu, tooltip_text='More'))
        view.add_top_bar(header)
        self.page = Adw.PreferencesPage()
        self.build()
        view.set_content(self.page)
        self.set_child(view)

    def build(self):
        game, ctx, state = self.game, self.ctx, self.state
        level, headline, description = model.headline(game, ctx)
        primary, secondary = self.main_actions()
        top = group()
        top.add(hero(game.title, level, headline, description, primary, secondary,
                     icon_name=STATE_ICONS[state][0] if state != 'available' else 'applications-games-symbolic'))
        self.page.add(top)
        if state == 'available':
            self.available()
        elif game.record and state not in ('unavailable',):
            self.overview()
            if state in ('installed', 'update', 'pinned', 'newer', 'outdated'):
                self.settings()
                self.updates()
            self.recovery()
        self.diagnostics()

    def main_actions(self):
        game, window, state = self.game, self.window, self.state
        if state == 'available':
            hard = model.refusals(game.verdict, 'hard')
            install = button('_Install…', lambda: window.install(game), 'pill', 'suggested-action')
            install.set_sensitive(game.checked and not hard and not model.refusals(game.verdict, 'risk'))
            return install, None
        if state == 'update':
            return button('_Update…', lambda: window.update_game(game), 'pill', 'suggested-action'), None
        if state == 'recovery':
            pending = (game.record or {}).get('pending_update') or {}
            if pending.get('generation'):
                return (button('_Finish Update', lambda: window.finish_update(game), 'pill', 'suggested-action'),
                        button('Undo _Update…', lambda: window.rollback(game, interrupted=True), 'pill'))
            return button('_Restore…', lambda: window.restore(game), 'pill', 'destructive-action'), None
        if state == 'outdated':
            return button('_Restore…', lambda: window.restore(game), 'pill'), None
        if state == 'pinned' and (game.record or {}).get('package') != self.ctx.release:
            return button('_Allow Updates', lambda: window.set_pin(game, False), 'pill'), None
        return None, None

    # not installed
    def available(self):
        game = self.game
        if not game.checked:
            waiting = group('Compatibility')
            row = action_row('Checking compatibility…', 'Reading the game folder. Nothing is changed.')
            row.add_suffix(spinner())
            waiting.add(row)
            self.page.add(waiting)
            return
        verdict = game.verdict
        found = group('Compatibility', 'What Install would do, from the game’s files, its launcher entry, the BC-250 '
                                       'recipes and the OptiScaler wiki. Nothing is changed.')
        blocking = model.refusals(verdict, 'hard', 'risk', 'soft')
        if not blocking:
            level, title, text = model.verdict_view(verdict)
            found.add(action_row(title or 'Compatibility', verdict['line'] if verdict else text, LEVEL_ICONS[level], level))
        for refusal in blocking:
            kind_level = 'warning' if refusal['kind'] == 'soft' else 'error'
            way = refusal['way']
            if refusal['code'] == 'anticheat' and model.override_available(verdict):
                way = 'Install refuses it. An override for this one game, at the risk of a ban, is below.'
            found.add(action_row(refusal['text'], way, LEVEL_ICONS[kind_level], kind_level))
        for warning in (verdict or {}).get('warnings', [])[:5]:
            found.add(action_row(warning, None, 'dialog-information-symbolic', 'dim'))
        self.page.add(found)
        steps = (verdict or {}).get('manual_steps') or []
        if steps and not model.refusals(verdict, 'hard'):
            later = group('After installing', 'Reopen your launcher. In the game:')
            for row in numbered(steps):
                later.add(row)
            self.page.add(later)
        if model.override_available(verdict):
            risk = group('Install despite anti-cheat', 'Anti-cheat software can answer injected DLLs with an account ban '
                                                       'or a refusal to start. Restore cannot undo a ban.')
            row = action_row('Override the anti-cheat refusal for this game', 'At your own risk; you will type a sentence '
                             'to confirm.', 'dialog-warning-symbolic', 'error')
            row.add_suffix(button('_Override…', lambda: self.window.override(game), 'destructive-action'))
            risk.add(row)
            self.page.add(risk)

    # installed
    def overview(self):
        game, ctx, record = self.game, self.ctx, self.game.record or {}
        setup = group('Configuration')
        upscaler = action_row('Upscaler', model.provider_label(record))
        if self.state not in ('recovery', 'attention'):
            upscaler.add_suffix(button('_Change…', lambda: self.window.change_upscaler(game), 'flat'))
        setup.add(upscaler)
        factor = (game.settings.factor if game.settings else 2)
        setup.add(action_row('Frame generation', f'{factor}× · {model.input_label(record)}'))
        if (record.get('compat') or {}).get('line'):
            setup.add(action_row('Compatibility at installation', record['compat']['line']))
        self.page.add(setup)
        health = group('Health', 'Logs describe the last recorded session; they do not prove current frame generation or '
                                 'visual correctness.')
        level, label, lines = model.session_view(game.run)
        session = plain(Adw.ExpanderRow(), 'Last session', label)
        session.add_prefix(icon(LEVEL_ICONS[level], level if level != 'neutral' else 'dim'))
        for line in lines:
            session.add_row(plain(Adw.ActionRow(), line))
        health.add(session)
        # Filled in by show_integrity once the files are hashed (off the window's thread).
        self.files_icon = Gtk.Stack()
        self.files_icon.add_named(spinner(), 'busy')
        self.files_row = action_row('Program files', 'Checking…')
        self.files_row.add_prefix(self.files_icon)
        health.add(self.files_row)
        self.launch_icon = Gtk.Stack()
        self.launch_icon.add_named(spinner(), 'busy')
        self.launch_row = action_row('Launch settings', ', '.join(
            str(t.get('launcher', '')).capitalize() for t in record.get('launchers') or []) or 'None recorded')
        self.launch_row.add_prefix(self.launch_icon)
        health.add(self.launch_row)
        for line in ctx.installer.risk_lines(record) if hasattr(ctx.installer, 'risk_lines') else []:
            health.add(action_row(line, 'Restore ends the override.', 'dialog-warning-symbolic', 'error'))
        self.page.add(health)
        if game.integrity is not None:
            self.show_integrity(game.integrity)

    def show_integrity(self, found):
        if not hasattr(self, 'files_row') or self.files_icon.get_child_by_name('done') is not None:
            return
        changed = found['changed']
        if changed:
            self.files_row.set_subtitle('Changed since installation: ' + ', '.join(changed[:3]) +
                                        (f' and {len(changed) - 3} more' if len(changed) > 3 else '') +
                                        '. A game update or another tool replaced them: restore, then install again.')
        else:
            self.files_row.set_subtitle('As installed')
        self.files_icon.add_named(icon('dialog-warning-symbolic' if changed else 'emblem-ok-symbolic',
                                       'warning' if changed else 'success'), 'done')
        self.files_icon.set_visible_child_name('done')
        launchers = found['launchers']
        ok = all(same for _, same in launchers)
        if launchers:
            self.launch_row.set_subtitle(', '.join(name + (' · as installed' if same else ' · changed since installation')
                                                   for name, same in launchers))
        self.launch_icon.add_named(icon('emblem-ok-symbolic' if ok else 'dialog-warning-symbolic',
                                        ('success' if ok else 'warning') if launchers else 'dim'), 'done')
        self.launch_icon.set_visible_child_name('done')

    def settings(self):
        game, ctx = self.game, self.ctx
        support = model.settings_support(game.record, len(ctx.factors) + 1)
        if not game.settings or not (support['scaling'] or len(support['factors']) > 1):
            return
        self.before = game.settings
        self.apply_button = button('_Apply', self.apply, 'suggested-action')
        self.revert_button = button('', self.revert, 'flat', icon_name='edit-undo-symbolic', tooltip='Revert')
        actions = Gtk.Box(spacing=6)
        actions.append(self.revert_button)
        actions.append(self.apply_button)
        self.settings_group = group('Settings', 'Apply when the game is closed; they take effect at its next start. '
                                                'OptiScaler offers the same controls in the game (Insert → Frame '
                                                'Generation → XeFG scaling).', suffix=actions)
        self.factor_row = None
        if len(support['factors']) > 1:
            self.factor_row = plain(Adw.ComboRow(), 'Frame generation')
            self.factor_row.set_model(Gtk.StringList.new([f'{n}×' for n in support['factors']]))
            self.factor_row.set_selected(max(0, support['factors'].index(game.settings.factor)
                                             if game.settings.factor in support['factors'] else 0))
            self.factors = support['factors']
            self.factor_row.connect('notify::selected', lambda *_: self.edited())
            self.settings_group.add(self.factor_row)
        self.size_row = self.scale_row = self.down_row = self.up_row = None
        if support['scaling']:
            self.size_row = plain(Adw.ComboRow(), 'Generated-frame size',
                                  'Only generated frames are scaled. Match output keeps full resolution.')
            self.size_row.set_model(Gtk.StringList.new([label for _, label in model.SIZES]))
            self.size_row.set_selected([key for key, _ in model.SIZES].index(game.settings.size))
            self.size_row.connect('notify::selected', lambda *_: self.edited())
            self.settings_group.add(self.size_row)
            self.scale_row = plain(Adw.SpinRow.new_with_range(50, 100, 1), 'Scale', 'Width and height, % of the output')
            self.scale_row.set_value(game.settings.percent)
            self.scale_row.connect('notify::value', lambda *_: self.edited())
            self.settings_group.add(self.scale_row)
            downs = model.DOWNSCALE if support['area'] else model.DOWNSCALE[:1]
            self.downs = [key for key, _ in downs]
            self.down_row = plain(Adw.ComboRow(), 'Downscale filter')
            self.down_row.set_model(Gtk.StringList.new([label for _, label in downs]))
            self.down_row.set_selected(self.downs.index(game.settings.downscale) if game.settings.downscale in self.downs else 0)
            self.down_row.connect('notify::selected', lambda *_: self.edited())
            self.settings_group.add(self.down_row)
            ups = model.UPSCALE if support['upscale'] else model.UPSCALE[:1]
            self.ups = [key for key, _ in ups]
            self.up_row = plain(Adw.ComboRow(), 'Upscale filter')
            self.up_row.set_model(Gtk.StringList.new([label for _, label in ups]))
            self.up_row.set_selected(self.ups.index(game.settings.upscale) if game.settings.upscale in self.ups else 0)
            self.up_row.connect('notify::selected', lambda *_: self.edited())
            self.settings_group.add(self.up_row)
        self.page.add(self.settings_group)
        self.edited()

    def chosen(self):
        settings = model.Settings(**vars(self.before))
        if self.factor_row is not None:
            settings.factor = self.factors[self.factor_row.get_selected()]
        if self.size_row is not None:
            settings.size = model.SIZES[self.size_row.get_selected()][0]
            settings.percent = int(self.scale_row.get_value())
            settings.downscale = self.downs[self.down_row.get_selected()]
            settings.upscale = self.ups[self.up_row.get_selected()]
        return settings

    def edited(self):
        after = self.chosen()
        if self.scale_row is not None:
            self.scale_row.set_visible(after.size == 'scale')
        changed = bool(model.settings_args(self.before, after))
        self.apply_button.set_visible(changed)
        self.revert_button.set_visible(changed)

    def revert(self):
        before = self.before
        if self.factor_row is not None and before.factor in self.factors:
            self.factor_row.set_selected(self.factors.index(before.factor))
        if self.size_row is not None:
            self.size_row.set_selected([key for key, _ in model.SIZES].index(before.size))
            self.scale_row.set_value(before.percent)
            self.down_row.set_selected(self.downs.index(before.downscale) if before.downscale in self.downs else 0)
            self.up_row.set_selected(self.ups.index(before.upscale) if before.upscale in self.ups else 0)
        self.edited()

    def apply(self):
        self.window.apply_settings(self.game, self.before, self.chosen())

    def updates(self):
        game, ctx, record = self.game, self.ctx, self.game.record or {}
        updates = group('Updates')
        if self.state == 'update':
            row = action_row(f'Update to {ctx.version}', f'From {model.version(record.get("package"))}. Shows the plan first.',
                             'software-update-available-symbolic', 'accent')
            row.add_suffix(button('_Update…', lambda: self.window.update_game(game), 'flat'))
            updates.add(row)
        pin = plain(Adw.SwitchRow(), 'Keep this release',
                    f'Update All leaves this game on {model.version(record.get("package"))}.')
        pin.set_active(bool(record.get('update_pin')))
        pin.connect('notify::active', lambda row, _p: row.get_active() != bool(record.get('update_pin')) and
                    self.window.set_pin(game, row.get_active()))
        updates.add(pin)
        if self.state in ('installed', 'update'):
            recipe = action_row('Refresh recipe', 'Apply the latest tested input and launcher recipe in place; game '
                                'settings stay manual. Shows the plan first.')
            recipe.add_suffix(button('_Preview…', lambda: self.window.update_game(game, refresh=True), 'flat'))
            updates.add(recipe)
        if not game.tracked and self.state in ('installed', 'update', 'pinned'):
            track = action_row('Not in Update All', 'No launcher entry or library record leads Update All here.',
                               'dialog-information-symbolic', 'dim')
            track.add_suffix(button('_Track', lambda: self.window.track(game), 'flat'))
            updates.add(track)
        self.page.add(updates)

    def recovery(self):
        game, record = self.game, self.game.record or {}
        recovery = group('Recovery')
        generations = record.get('generations') or []
        if generations and self.state != 'recovery':
            row = action_row('Roll back', f'Return to {model.version(generations[-1].get("from"))}, the release before the '
                             'last update or upscaler switch.')
            row.add_suffix(button('_Roll Back…', lambda: self.window.rollback(game), 'flat'))
            recovery.add(row)
        restore = action_row('Restore original files', f'Removes {self.ctx.name} from this game: its files, launch settings '
                             'and private shader cache. Backups and logs stay in the game folder.')
        restore.add_suffix(button('_Restore…', lambda: self.window.restore(game), 'flat', 'error'))
        recovery.add(restore)
        self.page.add(recovery)

    def diagnostics(self):
        game = self.game
        found = group('Diagnostics')
        if game.record:
            details = action_row('Installation details', 'Files, upscaler, launcher setup, recovery and the last session’s '
                                 'logs.')
            details.add_suffix(button('_Show…', lambda: self.window.status(game), 'flat'))
            found.add(details)
        report = action_row('Compatibility report', 'What Install would do, or why it refuses, with a redacted report for '
                            'a GitHub game report.')
        report.add_suffix(button('Sh_ow…', lambda: self.window.report(game), 'flat'))
        found.add(report)
        folder = action_row('Game folder', str(game.exe.parent))
        folder.add_suffix(button('', lambda: self.window.open_folder(game), 'flat', icon_name='folder-open-symbolic',
                                 tooltip='Open Game Folder'))
        found.add(folder)
        self.page.add(found)


# ------------------------------------------------------------------------------------------------- the application
class Application(Adw.Application):
    def __init__(self, ctx):
        slug = re.sub(r'[^a-z0-9]', '', ctx.name.lower()) or 'setup'
        super().__init__(application_id='io.github.' + slug + '.Setup', flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.ctx = ctx
        self.window = None
        self.failure = None
        self.connect('activate', self.activate_window)
        quit_action = Gio.SimpleAction.new('quit', None)
        quit_action.connect('activate', lambda *_: self.window.close() if self.window else self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action('app.quit', ['<Control>q'])
        self.set_accels_for_action('win.refresh', ['<Control>r', 'F5'])
        self.set_accels_for_action('win.search', ['<Control>f'])
        self.set_accels_for_action('win.add-exe', ['<Control>o'])

    def activate_window(self, *_):
        if self.window is None:
            try:
                provider = Gtk.CssProvider()
                provider.load_from_string(CSS)
                Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                          Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
                self.window = Window(self, self.ctx)
            except Exception as error:  # noqa: BLE001 - setup.py falls back to its dialogs
                self.failure = error
                self.quit()
                return
        self.window.present()


class StartupError(RuntimeError):
    """The window could not be built; setup.py then uses its Zenity dialogs."""


def run(ctx):
    """Show Setup's window for the package ctx describes; returns the exit status. Raises StartupError when the window
    cannot be built (setup.py falls back to its dialogs)."""
    if not Gtk.init_check():
        print('Setup needs a desktop session (Desktop Mode). The command-line route is in README.md.')
        return 1
    Gtk.Window.set_default_icon_name('applications-games')
    app = Application(ctx)
    status = app.run([])
    if app.failure is not None:
        raise StartupError(''.join(traceback.format_exception(app.failure)))
    return status
