use crate::exec_cell::spinner;
use crate::key_hint;
use crate::key_hint::KeyBinding;
use crate::render::line_utils::prefix_lines;
use crate::ui_consts::FOOTER_INDENT_COLS;
use crossterm::event::KeyCode;
use ratatui::buffer::Buffer;
use ratatui::layout::Rect;
use ratatui::style::Stylize;
use ratatui::text::Line;
use ratatui::text::Span;
use ratatui::widgets::Paragraph;
use ratatui::widgets::Widget;
use std::time::Duration;
use std::time::Instant;

#[derive(Clone, Copy, Debug)]
pub(crate) struct FooterProps {
    pub(crate) mode: FooterMode,
    pub(crate) esc_backtrack_hint: bool,
    pub(crate) use_shift_enter_hint: bool,
    pub(crate) is_task_running: bool,
    pub(crate) context_window_percent: Option<u8>,
    pub(crate) prompt_enhancement: Option<PromptEnhancementFooterState>,
    pub(crate) prompt_enhancer_enabled: bool,
    pub(crate) prompt_enhancement_history_available: bool,
}

#[derive(Clone, Copy, Debug)]
pub(crate) struct PromptEnhancementFooterState {
    pub(crate) started_at: Instant,
    pub(crate) timeout: Option<Duration>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum FooterMode {
    CtrlCReminder,
    ShortcutPrompt,
    ShortcutOverlay,
    EscHint,
    Enhancing,
    Empty,
}

pub(crate) fn toggle_shortcut_mode(current: FooterMode, ctrl_c_hint: bool) -> FooterMode {
    if ctrl_c_hint && matches!(current, FooterMode::CtrlCReminder) {
        return current;
    }

    match current {
        FooterMode::ShortcutOverlay | FooterMode::CtrlCReminder => FooterMode::ShortcutPrompt,
        FooterMode::Enhancing => FooterMode::Enhancing,
        _ => FooterMode::ShortcutOverlay,
    }
}

pub(crate) fn esc_hint_mode(current: FooterMode, is_task_running: bool) -> FooterMode {
    if is_task_running {
        current
    } else {
        FooterMode::EscHint
    }
}

pub(crate) fn reset_mode_after_activity(current: FooterMode) -> FooterMode {
    match current {
        FooterMode::EscHint
        | FooterMode::ShortcutOverlay
        | FooterMode::CtrlCReminder
        | FooterMode::Empty => FooterMode::ShortcutPrompt,
        other => other,
    }
}

pub(crate) fn footer_height(props: FooterProps) -> u16 {
    footer_lines(props).len() as u16
}

pub(crate) fn render_footer(area: Rect, buf: &mut Buffer, props: FooterProps) {
    Paragraph::new(prefix_lines(
        footer_lines(props),
        " ".repeat(FOOTER_INDENT_COLS).into(),
        " ".repeat(FOOTER_INDENT_COLS).into(),
    ))
    .render(area, buf);
}

fn footer_lines(props: FooterProps) -> Vec<Line<'static>> {
    match props.mode {
        FooterMode::CtrlCReminder => vec![ctrl_c_reminder_line(CtrlCReminderState {
            is_task_running: props.is_task_running,
        })],
        FooterMode::ShortcutPrompt => {
            if props.is_task_running {
                vec![context_window_line(props.context_window_percent)]
            } else {
                vec![Line::from(vec![
                    key_hint::plain(KeyCode::Char('?')).into(),
                    " for shortcuts".dim(),
                ])]
            }
        }
        FooterMode::ShortcutOverlay => shortcut_overlay_lines(ShortcutsState {
            use_shift_enter_hint: props.use_shift_enter_hint,
            esc_backtrack_hint: props.esc_backtrack_hint,
            prompt_enhancer_enabled: props.prompt_enhancer_enabled,
            prompt_enhancement_history_available: props.prompt_enhancement_history_available,
        }),
        FooterMode::EscHint => vec![esc_hint_line(props.esc_backtrack_hint)],
        FooterMode::Enhancing => vec![enhancing_line(
            props
                .prompt_enhancement
                .unwrap_or_else(default_prompt_enhancement_footer_state),
        )],
        FooterMode::Empty => Vec::new(),
    }
}

#[derive(Clone, Copy, Debug)]
struct CtrlCReminderState {
    is_task_running: bool,
}

#[derive(Clone, Copy, Debug)]
struct ShortcutsState {
    use_shift_enter_hint: bool,
    esc_backtrack_hint: bool,
    prompt_enhancer_enabled: bool,
    prompt_enhancement_history_available: bool,
}

fn ctrl_c_reminder_line(state: CtrlCReminderState) -> Line<'static> {
    let action = if state.is_task_running {
        "interrupt"
    } else {
        "quit"
    };
    Line::from(vec![
        key_hint::ctrl(KeyCode::Char('c')).into(),
        format!(" again to {action}").into(),
    ])
    .dim()
}

fn esc_hint_line(esc_backtrack_hint: bool) -> Line<'static> {
    let esc = key_hint::plain(KeyCode::Esc);
    if esc_backtrack_hint {
        Line::from(vec![esc.into(), " again to edit previous message".into()]).dim()
    } else {
        Line::from(vec![
            esc.into(),
            " ".into(),
            esc.into(),
            " to edit previous message".into(),
        ])
        .dim()
    }
}

fn shortcut_overlay_lines(state: ShortcutsState) -> Vec<Line<'static>> {
    let mut commands = Line::from("");
    let mut newline = Line::from("");
    let mut file_paths = Line::from("");
    let mut paste_image = Line::from("");
    let mut edit_previous = Line::from("");
    let mut quit = Line::from("");
    let mut show_transcript = Line::from("");

    for descriptor in SHORTCUTS {
        if let Some(text) = descriptor.overlay_entry(state) {
            match descriptor.id {
                ShortcutId::Commands => commands = text,
                ShortcutId::InsertNewline => newline = text,
                ShortcutId::FilePaths => file_paths = text,
                ShortcutId::PasteImage => paste_image = text,
                ShortcutId::EditPrevious => edit_previous = text,
                ShortcutId::Quit => quit = text,
                ShortcutId::ShowTranscript => show_transcript = text,
            }
        }
    }

    let ordered = vec![
        commands,
        newline,
        file_paths,
        paste_image,
        edit_previous,
        quit,
        Line::from(""),
        show_transcript,
    ];

    let mut lines = build_columns(ordered);

    if state.prompt_enhancer_enabled {
        lines.push(Line::from(""));
        lines.extend(prompt_enhancer_shortcut_lines(state));
    }

    lines
}

fn prompt_enhancer_shortcut_lines(state: ShortcutsState) -> Vec<Line<'static>> {
    if !state.prompt_enhancer_enabled {
        return Vec::new();
    }

    let restore_availability = if state.prompt_enhancement_history_available {
        "available now"
    } else {
        "after enhancement completes"
    };

    vec![
        vec![
            key_hint::ctrl(KeyCode::Char('p')).into(),
            " enhance prompt".into(),
        ]
        .into(),
        vec![
            key_hint::ctrl(KeyCode::Char('r')).into(),
            format!(" restore original ({restore_availability})").dim(),
        ]
        .into(),
        vec![
            key_hint::ctrl(KeyCode::Char('u')).into(),
            " clear composer".into(),
        ]
        .into(),
    ]
}

fn build_columns(entries: Vec<Line<'static>>) -> Vec<Line<'static>> {
    if entries.is_empty() {
        return Vec::new();
    }

    const COLUMNS: usize = 2;
    const COLUMN_PADDING: [usize; COLUMNS] = [4, 4];
    const COLUMN_GAP: usize = 4;

    let rows = entries.len().div_ceil(COLUMNS);
    let target_len = rows * COLUMNS;
    let mut entries = entries;
    if entries.len() < target_len {
        entries.extend(std::iter::repeat_n(
            Line::from(""),
            target_len - entries.len(),
        ));
    }

    let mut column_widths = [0usize; COLUMNS];

    for (idx, entry) in entries.iter().enumerate() {
        let column = idx % COLUMNS;
        column_widths[column] = column_widths[column].max(entry.width());
    }

    for (idx, width) in column_widths.iter_mut().enumerate() {
        *width += COLUMN_PADDING[idx];
    }

    entries
        .chunks(COLUMNS)
        .map(|chunk| {
            let mut line = Line::from("");
            for (col, entry) in chunk.iter().enumerate() {
                line.extend(entry.spans.clone());
                if col < COLUMNS - 1 {
                    let target_width = column_widths[col];
                    let padding = target_width.saturating_sub(entry.width()) + COLUMN_GAP;
                    line.push_span(Span::from(" ".repeat(padding)));
                }
            }
            line.dim()
        })
        .collect()
}

fn context_window_line(percent: Option<u8>) -> Line<'static> {
    let mut spans: Vec<Span<'static>> = Vec::new();
    match percent {
        Some(percent) => {
            spans.push(format!("{percent}%").dim());
            spans.push(" context left".dim());
        }
        None => {
            spans.push(key_hint::plain(KeyCode::Char('?')).into());
            spans.push(" for shortcuts".dim());
        }
    }
    Line::from(spans)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ShortcutId {
    Commands,
    InsertNewline,
    FilePaths,
    PasteImage,
    EditPrevious,
    Quit,
    ShowTranscript,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct ShortcutBinding {
    key: KeyBinding,
    condition: DisplayCondition,
}

impl ShortcutBinding {
    fn matches(&self, state: ShortcutsState) -> bool {
        self.condition.matches(state)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum DisplayCondition {
    Always,
    WhenShiftEnterHint,
    WhenNotShiftEnterHint,
}

impl DisplayCondition {
    fn matches(self, state: ShortcutsState) -> bool {
        match self {
            DisplayCondition::Always => true,
            DisplayCondition::WhenShiftEnterHint => state.use_shift_enter_hint,
            DisplayCondition::WhenNotShiftEnterHint => !state.use_shift_enter_hint,
        }
    }
}

struct ShortcutDescriptor {
    id: ShortcutId,
    bindings: &'static [ShortcutBinding],
    prefix: &'static str,
    label: &'static str,
}

impl ShortcutDescriptor {
    fn binding_for(&self, state: ShortcutsState) -> Option<&'static ShortcutBinding> {
        self.bindings.iter().find(|binding| binding.matches(state))
    }

    fn overlay_entry(&self, state: ShortcutsState) -> Option<Line<'static>> {
        let binding = self.binding_for(state)?;
        let mut line = Line::from(vec![self.prefix.into(), binding.key.into()]);
        match self.id {
            ShortcutId::EditPrevious => {
                if state.esc_backtrack_hint {
                    line.push_span(" again to edit previous message");
                } else {
                    line.extend(vec![
                        " ".into(),
                        key_hint::plain(KeyCode::Esc).into(),
                        " to edit previous message".into(),
                    ]);
                }
            }
            _ => line.push_span(self.label),
        };
        Some(line)
    }
}

const SHORTCUTS: &[ShortcutDescriptor] = &[
    ShortcutDescriptor {
        id: ShortcutId::Commands,
        bindings: &[ShortcutBinding {
            key: key_hint::plain(KeyCode::Char('/')),
            condition: DisplayCondition::Always,
        }],
        prefix: "",
        label: " for commands",
    },
    ShortcutDescriptor {
        id: ShortcutId::InsertNewline,
        bindings: &[
            ShortcutBinding {
                key: key_hint::shift(KeyCode::Enter),
                condition: DisplayCondition::WhenShiftEnterHint,
            },
            ShortcutBinding {
                key: key_hint::ctrl(KeyCode::Char('j')),
                condition: DisplayCondition::WhenNotShiftEnterHint,
            },
        ],
        prefix: "",
        label: " for newline",
    },
    ShortcutDescriptor {
        id: ShortcutId::FilePaths,
        bindings: &[ShortcutBinding {
            key: key_hint::plain(KeyCode::Char('@')),
            condition: DisplayCondition::Always,
        }],
        prefix: "",
        label: " for file paths",
    },
    ShortcutDescriptor {
        id: ShortcutId::PasteImage,
        bindings: &[ShortcutBinding {
            key: key_hint::ctrl(KeyCode::Char('v')),
            condition: DisplayCondition::Always,
        }],
        prefix: "",
        label: " to paste images",
    },
    ShortcutDescriptor {
        id: ShortcutId::EditPrevious,
        bindings: &[ShortcutBinding {
            key: key_hint::plain(KeyCode::Esc),
            condition: DisplayCondition::Always,
        }],
        prefix: "",
        label: "",
    },
    ShortcutDescriptor {
        id: ShortcutId::Quit,
        bindings: &[ShortcutBinding {
            key: key_hint::ctrl(KeyCode::Char('c')),
            condition: DisplayCondition::Always,
        }],
        prefix: "",
        label: " to exit",
    },
    ShortcutDescriptor {
        id: ShortcutId::ShowTranscript,
        bindings: &[ShortcutBinding {
            key: key_hint::ctrl(KeyCode::Char('t')),
            condition: DisplayCondition::Always,
        }],
        prefix: "",
        label: " to view transcript",
    },
];

fn enhancing_line(state: PromptEnhancementFooterState) -> Line<'static> {
    let spinner_span = spinner(Some(state.started_at));
    let elapsed = state.started_at.elapsed();
    let elapsed_span = Span::from(format!("{:.1}s elapsed", elapsed.as_secs_f32())).dim();
    let mut spans = vec![
        spinner_span,
        Span::from(" "),
        Span::from("Enhancing prompt…").dim(),
        Span::from(" "),
        elapsed_span,
    ];

    match state.timeout {
        Some(timeout) => {
            spans.push(Span::from(" / ").dim());
            spans.push(Span::from(format!("{:.1}s max", timeout.as_secs_f32())).dim());
            if elapsed >= timeout {
                spans.push(Span::from("  ·  "));
                spans.push(Span::from("Timed out!").red().bold());
            }
        }
        None => {
            spans.push(Span::from(" / ").dim());
            spans.push(Span::from("-- max").dim());
        }
    }

    spans.push(Span::from("  ·  "));
    spans.push(Span::from("Esc to cancel").dim());

    Line::from(spans)
}

fn default_prompt_enhancement_footer_state() -> PromptEnhancementFooterState {
    PromptEnhancementFooterState {
        started_at: Instant::now(),
        timeout: None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use insta::assert_snapshot;
    use ratatui::Terminal;
    use ratatui::backend::TestBackend;

    fn snapshot_footer(name: &str, props: FooterProps) {
        let height = footer_height(props).max(1);
        let mut terminal = Terminal::new(TestBackend::new(80, height)).unwrap();
        terminal
            .draw(|f| {
                let area = Rect::new(0, 0, f.area().width, height);
                render_footer(area, f.buffer_mut(), props);
            })
            .unwrap();
        assert_snapshot!(name, terminal.backend());
    }

    #[test]
    fn footer_snapshots() {
        snapshot_footer(
            "footer_shortcuts_default",
            FooterProps {
                mode: FooterMode::ShortcutPrompt,
                esc_backtrack_hint: false,
                use_shift_enter_hint: false,
                is_task_running: false,
                context_window_percent: None,
                prompt_enhancement: None,
                prompt_enhancer_enabled: false,
                prompt_enhancement_history_available: false,
            },
        );

        snapshot_footer(
            "footer_shortcuts_shift_and_esc",
            FooterProps {
                mode: FooterMode::ShortcutOverlay,
                esc_backtrack_hint: true,
                use_shift_enter_hint: true,
                is_task_running: false,
                context_window_percent: None,
                prompt_enhancement: None,
                prompt_enhancer_enabled: false,
                prompt_enhancement_history_available: false,
            },
        );

        snapshot_footer(
            "footer_ctrl_c_quit_idle",
            FooterProps {
                mode: FooterMode::CtrlCReminder,
                esc_backtrack_hint: false,
                use_shift_enter_hint: false,
                is_task_running: false,
                context_window_percent: None,
                prompt_enhancement: None,
                prompt_enhancer_enabled: false,
                prompt_enhancement_history_available: false,
            },
        );

        snapshot_footer(
            "footer_ctrl_c_quit_running",
            FooterProps {
                mode: FooterMode::CtrlCReminder,
                esc_backtrack_hint: false,
                use_shift_enter_hint: false,
                is_task_running: true,
                context_window_percent: None,
                prompt_enhancement: None,
                prompt_enhancer_enabled: false,
                prompt_enhancement_history_available: false,
            },
        );

        snapshot_footer(
            "footer_esc_hint_idle",
            FooterProps {
                mode: FooterMode::EscHint,
                esc_backtrack_hint: false,
                use_shift_enter_hint: false,
                is_task_running: false,
                context_window_percent: None,
                prompt_enhancement: None,
                prompt_enhancer_enabled: false,
                prompt_enhancement_history_available: false,
            },
        );

        snapshot_footer(
            "footer_esc_hint_primed",
            FooterProps {
                mode: FooterMode::EscHint,
                esc_backtrack_hint: true,
                use_shift_enter_hint: false,
                is_task_running: false,
                context_window_percent: None,
                prompt_enhancement: None,
                prompt_enhancer_enabled: false,
                prompt_enhancement_history_available: false,
            },
        );

        snapshot_footer(
            "footer_shortcuts_context_running",
            FooterProps {
                mode: FooterMode::ShortcutPrompt,
                esc_backtrack_hint: false,
                use_shift_enter_hint: false,
                is_task_running: true,
                context_window_percent: Some(72),
                prompt_enhancement: None,
                prompt_enhancer_enabled: false,
                prompt_enhancement_history_available: false,
            },
        );

        snapshot_footer(
            "footer_prompt_enhancing_waiting",
            FooterProps {
                mode: FooterMode::Enhancing,
                esc_backtrack_hint: false,
                use_shift_enter_hint: false,
                is_task_running: false,
                context_window_percent: None,
                prompt_enhancement: Some(PromptEnhancementFooterState {
                    started_at: Instant::now() - Duration::from_millis(2300),
                    timeout: Some(Duration::from_secs(8)),
                }),
                prompt_enhancer_enabled: true,
                prompt_enhancement_history_available: true,
            },
        );

        snapshot_footer(
            "footer_prompt_enhancing_timed_out",
            FooterProps {
                mode: FooterMode::Enhancing,
                esc_backtrack_hint: false,
                use_shift_enter_hint: false,
                is_task_running: false,
                context_window_percent: None,
                prompt_enhancement: Some(PromptEnhancementFooterState {
                    started_at: Instant::now() - Duration::from_secs(10),
                    timeout: Some(Duration::from_secs(8)),
                }),
                prompt_enhancer_enabled: true,
                prompt_enhancement_history_available: true,
            },
        );

        snapshot_footer(
            "footer_prompt_enhancer_shortcuts",
            FooterProps {
                mode: FooterMode::ShortcutOverlay,
                esc_backtrack_hint: false,
                use_shift_enter_hint: false,
                is_task_running: false,
                context_window_percent: None,
                prompt_enhancement: None,
                prompt_enhancer_enabled: true,
                prompt_enhancement_history_available: true,
            },
        );
    }
}
