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
SUMMARY_PHANTOM_SETS_BY_BUFFER = {}


class InlineErrorSettings:
    show_summary = None
    show_warnings = None
    show_errors = None
    inline_theme = None
    below_theme = None
    summary_inline_theme = None
    summary_below_theme = None
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
    summary_color = None
    summary_background_color = None
    inline_max_words = None
    font_size = None
    debug = None

    def __init__(self, on_change=None):
        s = sublime.load_settings('SublimeLinterInlineErrors.sublime-settings')
        fields = [f for f in dir(self) if not f.startswith('__')]
        for f in fields:
            setattr(self, f, s.get(f))
        if on_change:
            s.add_on_change('on_change_callback', on_change)


def print_debug(*args):
    global DEBUG
    if DEBUG is None:
        DEBUG = InlineErrorSettings().debug
    if DEBUG:
        'invalid syntax; SyntaxError'
        print('[INLINE ERRORS]', *args)


def plugin_loaded():
    global PHANTOM_SETS_BY_BUFFER
    global SUMMARY_PHANTOM_SETS_BY_BUFFER
    print_debug('Clear all phantoms')
    for _, phantom_set in PHANTOM_SETS_BY_BUFFER.items():
        phantom_set.update([])
    for _, phantom_set in SUMMARY_PHANTOM_SETS_BY_BUFFER.items():
        phantom_set.update([])


def plugin_unloaded():
    global PHANTOM_SETS_BY_BUFFER
    global SUMMARY_PHANTOM_SETS_BY_BUFFER
    print_debug('Clear all phantoms')
    for _, phantom_set in PHANTOM_SETS_BY_BUFFER.items():
        phantom_set.update([])
    for _, phantom_set in SUMMARY_PHANTOM_SETS_BY_BUFFER.items():
        phantom_set.update([])


class InlineErrors(sublime_plugin.ViewEventListener):
    _expanded_error_line = None
    linter = None
    _settings = None
    _current_line = -1
    _expand_summary = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.linter = Linter.shared_instance

        old_highlight = Linter.highlight
        _self = self

        def _highlight(self, view, linters, hit_time):
            res = old_highlight(self, view, linters, hit_time)
            _self.update_phantoms(force=True)
            return res
        Linter.highlight = _highlight

        old_clear = Linter.clear

        def _clear(self, view):
            res = old_clear(self, view)
            _self.clear(view)
            return res
        Linter.clear = _clear

    def settings(self):
        if self._settings is None:
            self._settings = InlineErrorSettings(
                self.on_settings_change.__get__(self, InlineErrors)
            )
        return self._settings

    def on_settings_change(self):
        self._settings = None
        self.update_phantoms(force=True)

    def on_selection_modified(self):
        self.update_phantoms()

    def get_template(self, theme_path):
        s = self.settings()

        if theme_path == 'none' or theme_path is None:
            return None

        tooltip_text = sublime.load_resource(theme_path)

        return Template(tooltip_text)

    def get_current_line(self):
        try:
            return self.view.rowcol(self.view.sel()[0].begin())[0]
        except IndexError:
            return -1

    def update_phantoms(self, force=False):
        linter = self.linter

        view = self.view

        if linter.is_scratch(view):
            return

        lineno = self.get_current_line()

        if not force and lineno == self._current_line:
            return

        self._current_line = lineno

        vid = view.id()

        if vid in persist.errors:
            errors = persist.errors[vid]

            self.show_phantoms(view, errors, lineno, persist.highlights[vid].all)

    def get_phantom_set(self, view):
        global PHANTOM_SETS_BY_BUFFER

        buffer_id = view.buffer_id()
        if buffer_id not in PHANTOM_SETS_BY_BUFFER:
            phantom_set = sublime.PhantomSet(view, 'linter-inline-errors')
            PHANTOM_SETS_BY_BUFFER[buffer_id] = phantom_set
        else:
            phantom_set = PHANTOM_SETS_BY_BUFFER[buffer_id]

        return phantom_set

    def get_summary_phantom_set(self, view):
        global SUMMARY_PHANTOM_SETS_BY_BUFFER

        buffer_id = view.buffer_id()
        if buffer_id not in SUMMARY_PHANTOM_SETS_BY_BUFFER:
            phantom_set = sublime.PhantomSet(view, 'linter-inline-errors-summary')
            SUMMARY_PHANTOM_SETS_BY_BUFFER[buffer_id] = phantom_set
        else:
            phantom_set = SUMMARY_PHANTOM_SETS_BY_BUFFER[buffer_id]

        return phantom_set

    def show_phantoms(self, view, errors, selected_line, highlights):
        s = self.settings()

        templates = {
            'inline': self.get_template(s.inline_theme),
            'below': self.get_template(s.below_theme)
        }

        if templates['inline'] is None or templates['below'] is None:
            return

        phantom_set = self.get_phantom_set(view)

        filtered_errors = self.filter_errors(errors, highlights)

        phantoms = [
            self.get_phantoms(line, line_errors, templates, view, selected_line == line)
            for (line, line_errors) in filtered_errors
        ]
        print_debug('Update phantoms: %s' % len(phantoms))
        phantom_set.update([p for pair in phantoms for p in pair if p])

        summary_phantom_set = self.get_summary_phantom_set(view)
        if s.show_summary and len(filtered_errors) > 0:
            summary_phantoms = self.get_summary_phantoms(filtered_errors)
            summary_phantom_set.update(summary_phantoms)
        else:
            summary_phantom_set.update([])

    def filter_errors(self, errors, highlights):
        s = self.settings()

        def filter_line_errors(line_errors, line):
            line_errors = sorted(line_errors, key=lambda error: error[0])
            line_errors = [(text, self.is_error(line, col, highlights)) for (col, text) in line_errors]

            if not s.show_warnings:
                line_errors = [(text, is_error) for (text, is_error) in line_errors if is_error]

            if not s.show_errors:
                line_errors = [(text, is_error) for (text, is_error) in line_errors if not is_error]

            return line_errors

        return [
            (line, filter_line_errors(errs, line)) for (line, errs) in errors.items()
        ]

    def clear(self, view):
        print_debug('Clear phantoms')
        view.erase_phantoms('linter-inline-errors')
        view.erase_phantoms('linter-inline-errors-summary')

    def is_error(self, row, col, highlights):
        pos = self.view.text_point(row, col)
        for h in highlights:
            if len([e for e in h.marks['error'] if e.a == pos]) > 0:
                return True

        return False

    def get_summary_phantoms(self, errors):
        s = self.settings()

        flatten_errors = [
            (line, text, is_error)
            for (line, line_errors) in errors
            for (text, is_error) in line_errors
        ]
        warnings_count = len([True for (_, _, is_error) in flatten_errors if not is_error])
        errors_count = len([True for (_, _, is_error) in flatten_errors if is_error])

        counters_message = [
            (('%s %s warnings' if warnings_count > 1 else '%s %s warning') % (s.warning_symbol, warnings_count)
                if warnings_count > 0 else ''),
            (('%s %s errors' if errors_count > 1 else '%s %s error') % (s.error_symbol, errors_count)
                if errors_count > 0 else '')
        ]
        counters_message = '; '.join([m for m in counters_message if m])

        summary_inline_template = self.get_template(s.summary_inline_theme)
        summary_below_template = self.get_template(s.summary_below_theme)

        if summary_inline_template is None or summary_below_template is None:
            return []

        counters_html = '<a href="%s">%s</a>' % ('toggle_summary', counters_message)

        if not self._expand_summary:
            errors_html = ''
        else:
            errors_html = ''.join([
                '<a href="%s" class="%s">%s: %s</a>' % (
                    line, 'summary_error' if is_error else 'summary_warning', line, t)
                for (line, text, is_error) in flatten_errors for t in self.wrap_text(text, is_error)
            ])

        region = self.view.line(self.view.text_point(0, 0))
        left_offset = self.get_left_offset(region, fit_text=counters_message)

        inline_content = summary_inline_template.substitute(
            counters=counters_html,
            font_size=s.font_size,
            left_offset='<div class="offset"> %s </div>' % (s.offset_symbol * left_offset),
            offset_color=s.offset_color,
            counters_background_color=(
                'background-color: #%s;' % s.summary_background_color
                if s.summary_background_color else ''
            ),
            counters_color='color: #%s;' % s.summary_color if s.summary_color else ''
        )

        inline_phantom = sublime.Phantom(
            sublime.Region(region.b, region.b),
            inline_content,
            sublime.LAYOUT_INLINE,
            on_navigate=self.on_summary_navigate.__get__(self, InlineErrors)
        )

        if self._expand_summary:
            below_content = summary_below_template.substitute(
                message=errors_html,
                font_size=s.font_size,
                warning_background_color=(
                    'background-color: #%s;' % s.below_warning_background_color
                    if s.below_warning_background_color else ''
                ),
                warning_color='color: #%s;' % s.below_warning_color if s.below_warning_color else '',
                error_background_color=(
                    'background-color: #%s;' % s.below_error_background_color
                    if s.below_error_background_color else ''
                ),
                error_color='color: #%s;' % s.below_error_color if s.below_error_color else ''
            )

            line_text = self.view.substr(region)
            match = re.search(r'[^\s]', line_text)
            line_offset = (region.a + match.start()) if match else region.b

            below_phantom = sublime.Phantom(
                sublime.Region(line_offset, line_offset),
                below_content,
                sublime.LAYOUT_BELOW,
                on_navigate=self.on_summary_navigate.__get__(self, InlineErrors)
            )

            return [inline_phantom, below_phantom]

        return [inline_phantom]

    def on_summary_navigate(self, text):
        if text == 'toggle_summary':
            self._expand_summary = not self._expand_summary
            self.update_phantoms(force=True)
        else:
            line = int(text)
            self.view.show(self.view.text_point(line, 0))

    def wrap_text(self, text, is_error):
        s = self.settings()
        hint_symbol = s.error_symbol if is_error else s.warning_symbol
        wrapped = textwrap.wrap(text, s.max_block_width, break_long_words=False)
        text_lines = [
            ('%s %s' % (hint_symbol, escape(l))
             if idx == 0 else '<div class="pad">%s</div>' % escape(l))
            for (idx, l) in enumerate(wrapped)
        ]

        return text_lines

    def get_viewport_width(self):
        return int(self.view.viewport_extent()[0] / self.view.em_width()) - 3

    def get_left_offset(self, region, fit_text=None):
        s = self.settings()
        line_width = region.b - region.a
        left_offset = max(s.min_offset - line_width, s.min_gap)

        offset_overflow = line_width + left_offset - self.get_viewport_width() + 4
        if fit_text is not None:
            offset_overflow = offset_overflow + len(fit_text)
        if offset_overflow > 0:
            left_offset = max(0, left_offset - offset_overflow)

        return left_offset

    def get_phantoms(self, line, line_errors, templates, view, is_selected):
        s = self.settings()

        region = view.line(view.text_point(line, 0))
        line_width = region.b - region.a
        left_offset = self.get_left_offset(region)
        is_expanded = line == self._expanded_error_line or s.hint_on_selected_line == 'below' and is_selected

        if s.hint_on_selected_line == 'none' and is_selected and not is_expanded:
            return (None, None)

        has_inline_text = s.show_inline_text and not is_expanded and (
            not is_selected or s.hint_on_selected_line == 'inline'
        )
        inline_text = '; '.join([l for (l, is_error) in line_errors])

        if s.inline_max_words:
            inline_text_words = inline_text.split(' ')
            if len(inline_text_words) > s.inline_max_words:
                inline_text = '%s…' % ' '.join(inline_text_words[:s.inline_max_words])

        viewport_width = self.get_viewport_width()

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
            for (text, is_error) in line_errors for l in self.wrap_text(text, is_error)
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

        self.update_phantoms(force=True)

    def set_cursor(self):
        pass
        # self.view.sel().clear()
        # self.view.sel().add(sublime.Region(0, 0))

    def on_activated_async(self):
        self.update_phantoms()
