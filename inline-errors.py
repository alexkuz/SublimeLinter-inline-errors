import re
from cgi import escape
from string import Template
import textwrap
import sublime
import sublime_plugin
from SublimeLinter.sublimelinter import SublimeLinter as Linter
from SublimeLinter.lint import persist, highlight

DEBUG = None

PHANTOM_SETS_BY_BUFFER = {}


class InlineErrorSettings:
    inline_theme = None
    below_theme = None
    hint_on_selected_line = None
    min_offset = None
    max_block_width = None
    min_gap = None
    show_inline_text = None
    warning_symbol = None
    error_symbol = None
    offset_symbol = None
    offset_color = None
    inline_warning_color = None
    inline_warning_background_color = None
    inline_error_color = None
    inline_error_background_color = None
    below_warning_color = None
    below_warning_background_color = None
    below_error_color = None
    below_error_background_color = None
    inline_max_words = None
    font_size = None
    debug = None

    def __init__(self):
        s = sublime.load_settings('SublimeLinterInlineErrors.sublime-settings')
        fields = [f for f in dir(self) if not f.startswith('__')]
        for f in fields:
            setattr(self, f, s.get(f))


def print_debug(*args):
    global DEBUG
    if DEBUG is None:
        DEBUG = InlineErrorSettings().debug
    if DEBUG:
        'invalid syntax; SyntaxError'
        print('[INLINE ERRORS]', *args)


def plugin_loaded():
    global PHANTOM_SETS_BY_BUFFER
    print_debug('Clear all phantoms')
    for _, phantom_set in PHANTOM_SETS_BY_BUFFER.items():
        phantom_set.update([])


def plugin_unloaded():
    global PHANTOM_SETS_BY_BUFFER
    print_debug('Clear all phantoms')
    for _, phantom_set in PHANTOM_SETS_BY_BUFFER.items():
        phantom_set.update([])


class InlineErrors(sublime_plugin.ViewEventListener):
    _expanded_error_line = None
    linter = None
    _settings = None

    def settings(self):
        if self._settings is None:
            self._settings = InlineErrorSettings()
        return self._settings

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.linter = Linter.shared_instance

        old_highlight = Linter.highlight
        _self = self

        def _highlight(self, view, linters, hit_time):
            res = old_highlight(self, view, linters, hit_time)
            _self.on_selection_modified()
            return res
        Linter.highlight = _highlight

        old_clear = Linter.clear

        def _clear(self, view):
            res = old_clear(self, view)
            _self.clear(view)
            return res
        Linter.clear = _clear

    def get_template(self, layout):
        if layout == sublime.LAYOUT_INLINE:
            theme_path = self.settings().inline_theme
        elif layout == sublime.LAYOUT_BELOW:
            theme_path = self.settings().below_theme

        if theme_path == 'none' or theme_path is None:
            return False

        tooltip_text = sublime.load_resource(theme_path)

        return Template(tooltip_text)

    def on_selection_modified(self):
        linter = self.linter

        view = self.view

        if linter.is_scratch(view):
            return

        vid = view.id()

        # Get the line number of the first line of the first selection.
        try:
            lineno = view.rowcol(view.sel()[0].begin())[0]
        except IndexError:
            lineno = -1

        if vid in persist.errors:
            errors = persist.errors[vid]

            self.show_phantom(view, errors, lineno, persist.highlights[vid].all)

    def get_phantom_set(self, view):
        global PHANTOM_SETS_BY_BUFFER
        buffer_id = view.buffer_id()
        if buffer_id not in PHANTOM_SETS_BY_BUFFER:
            phantom_set = sublime.PhantomSet(view, 'linter-inline-errors')
            PHANTOM_SETS_BY_BUFFER[buffer_id] = phantom_set
        else:
            phantom_set = PHANTOM_SETS_BY_BUFFER[buffer_id]

        return phantom_set

    def show_phantom(self, view, errors, selected_line, highlights):
        templates = {
            'inline': self.get_template(sublime.LAYOUT_INLINE),
            'below': self.get_template(sublime.LAYOUT_BELOW)
        }

        if not templates['inline'] or not templates['below']:
            return

        phantom_set = self.get_phantom_set(view)

        phantoms = [
            self.get_phantoms(line, errs, templates, view, selected_line == line, highlights)
            for line, errs in errors.items()
        ]
        print_debug('Update phantoms: %s' % len(phantoms))
        phantom_set.update([p for pair in phantoms for p in pair if p])

    def clear(self, view):
        print_debug('Clear phantoms')
        view.erase_phantoms('linter-inline-errors')

    def is_error(self, row, col, highlights):
        pos = self.view.text_point(row, col)
        for h in highlights:
            if len([e for e in h.marks['error'] if e.a == pos]) > 0:
                return True

        return False

    def get_phantoms(self, line, errors, templates, view, is_selected, highlights):

        line_errors = sorted(errors, key=lambda error: error[0])
        line_errors = [(error[1], self.is_error(line, error[0], highlights)) for error in line_errors]

        s = self.settings()

        region = view.line(view.text_point(line, 0))
        line_width = region.b - region.a
        left_offset = max(s.min_offset - line_width, s.min_gap)
        is_expanded = line == self._expanded_error_line or s.hint_on_selected_line == 'below' and is_selected

        if s.hint_on_selected_line == 'none' and is_selected and not is_expanded:
            return (None, None)

        def wrap_line(line, is_error):
            hint_symbol = s.error_symbol if is_error else s.warning_symbol
            wrapped = textwrap.wrap(line, s.max_block_width, break_long_words=False)
            lines = [
                ('%s %s' % (hint_symbol, escape(l))
                 if idx == 0 else '<div class="pad">%s</div>' % escape(l))
                for (idx, l) in enumerate(wrapped)
            ]

            return lines

        has_inline_text = s.show_inline_text and not is_expanded and (
            not is_selected or s.hint_on_selected_line == 'inline'
        )
        inline_text = '; '.join([l[0] for l in line_errors])

        if s.inline_max_words:
            inline_text_words = inline_text.split(' ')
            if len(inline_text_words) > s.inline_max_words:
                inline_text = '%s…' % ' '.join(inline_text_words[:s.inline_max_words])

        viewport_width = int(self.view.viewport_extent()[0] / self.view.em_width()) - 3

        offset_overflow = (region.b - region.a) + left_offset - viewport_width + 4
        if offset_overflow > 0:
            left_offset = max(0, left_offset - offset_overflow)

        if is_selected:
            hint_overflow = (region.b - region.a) + left_offset + len(inline_text) - viewport_width + 4
            if hint_overflow > 0:
                fixed_width = len(inline_text) - hint_overflow - 1
                inline_text = '%s…' % inline_text[:fixed_width] if fixed_width > 0 else ''

        has_error = len([is_error for (l, is_error) in line_errors if is_error]) > 0
        hint_symbol = s.error_symbol if has_error else s.warning_symbol
        classname = 'inline_error' if has_error else 'inline_warning'
        inline_message = (
            '<a href="%s" class="%s">%s %s</a>' % (line, classname, hint_symbol, escape(inline_text))
            if has_inline_text else ''
        )
        below_message = ''.join([
            '<a href="%s" class="%s">%s</a>' % (line, 'below_error' if is_error else 'below_warning', l)
            for (lines, is_error) in line_errors for l in wrap_line(lines, is_error)
        ])

        line_text = view.substr(region)
        match = re.search(r'[^\s]', line_text)
        line_offset = (region.a + match.start()) if match else region.b

        inline_tooltip_content = templates['inline'].substitute(
            line=line,
            left_offset='<div class="offset"> %s </div>' % (s.offset_symbol * left_offset),
            message='<a href="%s">%s</a>' % (line, hint_symbol) if not has_inline_text else inline_message,
            font_size=s.font_size,
            offset_color=s.offset_color,
            warning_background_color=(
                'background-color: #%s;' % s.inline_warning_background_color
                if s.inline_warning_background_color else ''
            ),
            warning_color='color: #%s;' % s.inline_warning_color if s.inline_warning_color else '',
            error_background_color=(
                'background-color: #%s;' % s.inline_error_background_color
                if s.inline_error_background_color else ''
            ),
            error_color='color: #%s;' % s.inline_error_color if s.inline_error_color else ''
        )

        below_tooltip_content = templates['below'].substitute(
            line=line,
            left_offset='',
            message=below_message,
            font_size=s.font_size,
            warning_background_color=(
                'background-color: #%s;' % s.below_warning_background_color
                if s.below_warning_background_color else ''
            ),
            error_background_color=(
                'background-color: #%s;' % s.below_error_background_color
                if s.below_error_background_color else ''
            ),
            warning_color='color: #%s;' % s.below_warning_color if s.below_warning_color else '',
            error_color='color: #%s;' % s.below_error_color if s.below_error_color else ''
        )

        inline_phantom = sublime.Phantom(
            sublime.Region(region.b, region.b),
            inline_tooltip_content,
            sublime.LAYOUT_INLINE,
            on_navigate=self.on_navigate.__get__(self, InlineErrors)
        )

        below_phantom = sublime.Phantom(
            sublime.Region(line_offset, line_offset),
            below_tooltip_content,
            sublime.LAYOUT_BELOW,
            on_navigate=self.on_navigate.__get__(self, InlineErrors)
        )

        return (inline_phantom, below_phantom if is_expanded else None)

    def on_navigate(self, text):
        if text == 'margin':
            sublime.set_timeout(self.set_cursor.__get__(self, InlineErrors), 100)
            return

        line = int(text)

        self._expanded_error_line = line if self._expanded_error_line != line else None

        self.on_selection_modified()

    def set_cursor(self):
        pass
        # self.view.sel().clear()
        # self.view.sel().add(sublime.Region(0, 0))

    def on_activated_async(self):
        self.on_selection_modified()
