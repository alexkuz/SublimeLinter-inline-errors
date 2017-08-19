# SublimeLinter-inline-errors
Shows linting errors inline with Phantom API

Much experimental. Very beta.

Works like this:

![](https://media.giphy.com/media/xT39CTcPGpMUcVKHQs/giphy.gif)

Or this:

![](https://media.giphy.com/media/l41JK9BsUAhlWLB6M/giphy.gif)

## Installation

- Open `Package Control: Install Package`
- Find and install `SublimeLinter Inline Errors` package

## Settings

```js
{
  // Hint font size
  "font_size": "0.9rem",

  // If true, shows hint inline, otherwise below the line
  "show_inline_text": true,

  // Hint behaviour when caret is on hinted line
  //
  // "inline" - shows inline hint
  // "below" - shows hint below the line
  // "none" - hides hint
  "hint_on_selected_line": "none",

  // Most left position for the hint in line (unless viewport is narrower than that)
  "min_offset": 100,

  // Max width for the block shown below the line
  "max_block_width": 80,

  // Minimal gap between the text line and the hint
  "min_gap": 5,

  // Theme file for inline hints
  "inline_theme": "Packages/SublimeLinter Inline Errors/themes/inline.html",

  // Theme file for below-the-line hints
  "below_theme": "Packages/SublimeLinter Inline Errors/themes/below.html",

  // Symbol used as a warning hint prefix
  "warning_symbol": "⚠️",

  // Symbol used as an error hint prefix
  "error_symbol": "⛔",

  // Symbol used in the offset
  "offset_symbol": "&nbsp;",

  // Offset symbol color (set your background color here to hide the offset symbols)
  "offset_color": "553333",

  // Inline warning text color
  "inline_warning_color": "DDCC66",

  // Inline warning background color
  "inline_warning_background_color": "",

  // Inline error text color
  "inline_error_color": "DD6666",

  // Inline error background color
  "inline_error_background_color": "",

  // Below-the-line warning text color
  "below_warning_color": "FFFFFF",

  // Below-the-line warning background color
  "below_warning_background_color": "BBAA33",

  // Below-the-line error text color
  "below_error_color": "FFFFFF",

  // Below-the-line error background color
  "below_error_background_color": "993333",

  // Maximum number of words in inline hint
  "inline_max_words": 30,

  // Prints debug messages in console
  "debug": false
}
```
