import re
from string import Template
import textwrap
import sublime
import sublime_plugin
from SublimeLinter.sublimelinter import SublimeLinter as Linter
from SublimeLinter.lint import persist

PHANTOM_SETS_BY_BUFFER = {}


def settings():
    return sublime.load_settings('SublimeLinterInlineErrors.sublime-settings')


def print_debug(*args):
    if settings().get('debug'):
        'invalid syntax; SyntaxError'
        print('[INLINE ERRORS]', *args)


def plugin_loaded():
    print_debug('Clear all phantoms')
    for _, phantom_set in PHANTOM_SETS_BY_BUFFER.items():
        phantom_set.update([])


def plugin_unloaded():
    print_debug('Clear all phantoms')
    for _, phantom_set in PHANTOM_SETS_BY_BUFFER.items():
        phantom_set.update([])


class InlineErrors(sublime_plugin.ViewEventListener):
    _expanded_error_line = None
    linter = None

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

    def get_template(self, theme_name):
        theme_path = settings().get(theme_name)

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

            self.show_phantom(view, errors, lineno)

    def get_phantom_set(self, view):
        buffer_id = view.buffer_id()
        if buffer_id not in PHANTOM_SETS_BY_BUFFER:
            phantom_set = sublime.PhantomSet(view, 'linter-inline-errors')
            PHANTOM_SETS_BY_BUFFER[buffer_id] = phantom_set
        else:
            phantom_set = PHANTOM_SETS_BY_BUFFER[buffer_id]

        return phantom_set

    def show_phantom(self, view, errors, selected_line):
        templates = {
            'inline': self.get_template('inline_theme'),
            'below': self.get_template('below_theme')
        }

        if not templates['inline'] or not templates['below']:
            return

        phantom_set = self.get_phantom_set(view)

        phantoms = [
            self.get_phantoms(line, errs, templates, view, selected_line == line)
            for line, errs in errors.items()
        ]
        print_debug('Update phantoms: %s' % len(phantoms))
        phantom_set.update([p for pair in phantoms for p in pair if p])

    def clear(self, view):
        phantom_set = self.get_phantom_set(view)
        print_debug('Clear phantoms')
        phantom_set.update([])

    def get_phantoms(self, line, errors, templates, view, is_selected):
        hint_on_selected_line = settings().get('hint_on_selected_line')

        line_errors = sorted(errors, key=lambda error: error[0])
        line_errors = [error[1] for error in line_errors]

        s = settings()
        min_offset = s.get('min_offset')
        max_block_width = s.get('max_block_width')
        min_gap = s.get('min_gap')
        show_inline_text = s.get('show_inline_text')
        warning_symbol = s.get('warning_symbol')
        offset_symbol = s.get('offset_symbol')
        offset_color = s.get('offset_color')
        inline_hint_color = s.get('inline_hint_color')
        inline_hint_background_color = s.get('inline_hint_background_color')
        below_hint_color = s.get('below_hint_color')
        below_hint_background_color = s.get('below_hint_background_color')
        inline_max_words = s.get('inline_max_words')
        font_size = s.get('font_size')

        region = view.line(view.text_point(line, 0))
        line_width = region.b - region.a
        left_offset = max(min_offset - line_width, min_gap)
        is_expanded = line == self._expanded_error_line or hint_on_selected_line == 'below' and is_selected

        if hint_on_selected_line == 'none' and is_selected and not is_expanded:
            return (None, None)

        def wrap_line(line):
            wrapped = textwrap.wrap(line, max_block_width, break_long_words=False)
            return [
                ('%s %s' % (warning_symbol, l)
                 if idx == 0 else '<div class="pad">%s</div>' % l)
                for (idx, l) in enumerate(wrapped)
            ]

        has_inline_text = show_inline_text and not is_expanded and (
            not is_selected or hint_on_selected_line == 'inline'
        )
        inline_text = '; '.join(line_errors)

        if inline_max_words:
            inline_text_words = inline_text.split(' ')
            if len(inline_text_words) > inline_max_words:
                inline_text = '%s…' % ' '.join(inline_text_words[:inline_max_words])

        viewport_width = int(self.view.viewport_extent()[0] / self.view.em_width()) - 3

        offset_overflow = (region.b - region.a) + left_offset - viewport_width + 4
        if offset_overflow > 0:
            left_offset = max(0, left_offset - offset_overflow)

        if is_selected:
            hint_overflow = (region.b - region.a) + left_offset + len(inline_text) - viewport_width + 4
            print((region.b - region.a) + left_offset + len(inline_text), viewport_width)
            if hint_overflow > 0:
                fixed_width = len(inline_text) - hint_overflow - 1
                inline_text = '%s…' % inline_text[:fixed_width] if fixed_width > 0 else ''

        inline_message = '<a href="%s">%s %s</a>' % (line, warning_symbol, inline_text) if has_inline_text else ''
        below_message = ''.join(['<a href="%s">%s</a>' % (line, l) for e in line_errors for l in wrap_line(e)])

        line_text = view.substr(region)
        match = re.search(r'[^\s]', line_text)
        line_offset = (region.a + match.start()) if match else region.b

        inline_tooltip_content = templates['inline'].substitute(
            line=line,
            left_offset='<div class="offset"> %s </div>' % (offset_symbol * left_offset),
            message='<a href="%s">%s</a>' % (line, warning_symbol) if not has_inline_text else inline_message,
            font_size=font_size,
            offset_color=offset_color,
            hint_background_color=(
                'background-color: #%s;' % inline_hint_background_color
                if inline_hint_background_color else ''
            ),
            hint_color='color: #%s;' % inline_hint_color if inline_hint_color else ''
        )

        below_tooltip_content = templates['below'].substitute(
            line=line,
            left_offset='',
            message=below_message,
            font_size=font_size,
            hint_background_color=(
                'background-color: #%s;' % below_hint_background_color
                if below_hint_background_color else ''
            ),
            hint_color='color: #%s;' % below_hint_color if below_hint_color else ''
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
