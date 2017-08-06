import re
import os
from string import Template
import textwrap
import sublime
import sublime_plugin
from SublimeLinter.sublimelinter import SublimeLinter as Linter
from SublimeLinter.lint import persist

class InlineErrors(sublime_plugin.EventListener):
    _expanded_error_line = None
    _phantom_sets_by_buffer = {}
    linter = None
    settings = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.linter = Linter.shared_instance

        old_highlight = Linter.highlight
        _self = self
        def _highlight(self, view, linters, hit_time):
            res = old_highlight(self, view, linters, hit_time)
            _self.on_selection_modified_async(view)
            return res
        Linter.highlight = _highlight

        old_clear = Linter.clear
        def _clear(self, view):
            res = old_clear(self, view)
            _self.clear(view)
            return res
        Linter.clear = _clear

        self.clear(sublime.active_window().active_view())

    def get_template(self, theme_name):
        theme_path = self.settings.get(theme_name)

        if theme_path == 'none' or theme_path == None:
            return False

        tooltip_text = sublime.load_resource(theme_path)

        return Template(tooltip_text)


    def on_selection_modified_async(self, view):
        linter = self.linter

        if linter.is_scratch(view):
            return

        view = linter.get_focused_view_id(view)

        if view is None:
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
        if buffer_id not in self._phantom_sets_by_buffer:
            phantom_set = sublime.PhantomSet(view, 'linter-inline-errors')
            self._phantom_sets_by_buffer[buffer_id] = phantom_set
        else:
            phantom_set = self._phantom_sets_by_buffer[buffer_id]

        return phantom_set

    def show_phantom(self, view, errors, selected_line):
        self.settings = sublime.load_settings('SublimeLinter-inline-errors.sublime-settings')

        templates = {
            'inline': self.get_template('inline_theme'),
            'below': self.get_template('below_theme')
        }

        if not templates['inline'] or not templates['below']:
            print('NO TEMPLATES')
            return

        phantom_set = self.get_phantom_set(view)

        phantoms = [self.get_phantoms(line, errs, templates, view, selected_line == line) for line, errs in errors.items()]
        phantom_set.update([p for pair in phantoms for p in pair if p])

    def clear(self, view):
        phantom_set = self.get_phantom_set(view)
        phantom_set.update([])

    def get_phantoms(self, line, errors, templates, view, is_selected):
        inline_text_on_selected_line = self.settings.get('inline_text_on_selected_line')

        line_errors = sorted(errors, key=lambda error: error[0])
        line_errors = [error[1] for error in line_errors]

        min_width = self.settings.get('min_width')
        max_block_width = self.settings.get('max_block_width')
        min_gap = self.settings.get('min_gap')
        show_inline_text = self.settings.get('show_inline_text')
        warning_symbol = self.settings.get('warning_symbol')
        offset_symbol = self.settings.get('offset_symbol')
        offset_color = self.settings.get('offset_color')
        inline_error_color = self.settings.get('inline_error_color')
        inline_error_background_color = self.settings.get('inline_error_background_color')
        below_error_color = self.settings.get('below_error_color')
        below_error_background_color = self.settings.get('below_error_background_color')
        inline_max_words = self.settings.get('inline_max_words')

        region = view.line(view.text_point(line, 0))
        line_width = region.b - region.a
        left_margin = max(min_width - line_width, min_gap)
        is_expanded = line == self._expanded_error_line or inline_text_on_selected_line == "below" and is_selected

        if inline_text_on_selected_line == "none" and is_selected and not is_expanded:
            return (None, None)

        def wrap_line(line):
            wrapped = textwrap.wrap(line, max_block_width, break_long_words=False)
            return [('%s %s' % (warning_symbol, l) if idx == 0 else '<div class="pad">%s</div>' % l) for (idx, l) in enumerate(wrapped)]

        has_inline_text = show_inline_text and not is_expanded and not is_selected
        inline_text = '; '.join(line_errors)
        if inline_max_words:
            inline_text_words = inline_text.split(' ')
            if len(inline_text_words) > inline_max_words:
                inline_text = '%s…' % ' '.join(inline_text_words[:inline_max_words])

        inline_message = '<a href="%s">%s %s</a>' % (line, warning_symbol, inline_text) if has_inline_text else ''
        below_message = ''.join(['<a href="%s">%s</a>' % (line, l) for e in line_errors for l in wrap_line(e)])

        line_text = view.substr(region)
        match = re.search(r'[^\s]', line_text)
        line_offset = (region.a + match.start()) if match else region.b

        inline_tooltip_content = templates['inline'].substitute(
            line=line,
            left_margin='<i class="margin"> %s </i>' % (offset_symbol * left_margin),
            message='<a href="%s">%s</a>' % (line, warning_symbol) if not has_inline_text else inline_message,
            font_size=self.settings.get('fontsize'),
            link_display='inline',
            offset_color=offset_color,
            error_background_color='background-color: #%s;' % inline_error_background_color if inline_error_background_color else '',
            error_color='color: #%s;' % inline_error_color if inline_error_color else ''
        )

        below_tooltip_content = templates['below'].substitute(
            line=line,
            left_margin='',
            message=below_message,
            font_size=self.settings.get('fontsize'),
            link_display='block',
            error_background_color='background-color: #%s;' % below_error_background_color if below_error_background_color else '',
            error_color='color: #%s;' % below_error_color if below_error_color else ''
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
        line = int(text)

        self._expanded_error_line = line if self._expanded_error_line != line else None

        self.on_selection_modified_async(sublime.active_window().active_view())

    def on_activated_async(self, view):
        self.on_selection_modified_async(view)
