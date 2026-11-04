//! AgentNav palettes (fork of Herdr kept by Pablo's AgentNav).
//!
//! Five extra built-in themes that show up in Settings next to the official ones:
//! `cs16` (Counter-Strike 1.6 / GoldSrc console), `matrix`, `procomm` (Procomm Plus for DOS),
//! `ambar` (amber-phosphor retro monitor) and `miami` (Vice City sunset: violet, magenta, coral, orange).
//! Everything else about themes is upstream code; this file only adds constructors, and the
//! hooks are small insertions in `config/theme.rs` (names) and `app/state.rs` (`from_name`).
//! The sidebar background stays `Color::Reset`, like every upstream theme, so the host terminal
//! background shows through; the contrast rules of the upstream tests hold for all of them.

use super::state::Palette;
use ratatui::style::Color;

impl Palette {
    /// Counter-Strike 1.6 console: olive-green panels, sand text, orange accent.
    pub fn cs16() -> Self {
        Self {
            accent: Color::Rgb(227, 169, 59),
            panel_bg: Color::Rgb(59, 69, 49),
            sidebar_bg: Color::Reset,
            active_row_bg: Color::Rgb(76, 88, 68),
            selection_bg: Color::Rgb(90, 102, 80),
            surface0: Color::Rgb(70, 81, 60),
            surface1: Color::Rgb(82, 94, 71),
            surface_dim: Color::Rgb(42, 49, 34),
            overlay0: Color::Rgb(122, 138, 106),
            overlay1: Color::Rgb(147, 163, 131),
            text: Color::Rgb(212, 201, 154),
            subtext0: Color::Rgb(169, 160, 122),
            mauve: Color::Rgb(201, 169, 107),
            green: Color::Rgb(143, 188, 90),
            yellow: Color::Rgb(240, 192, 75),
            red: Color::Rgb(217, 88, 59),
            blue: Color::Rgb(141, 166, 140),
            teal: Color::Rgb(159, 191, 138),
            peach: Color::Rgb(255, 159, 39),
        }
    }

    /// Matrix: black and phosphor green.
    pub fn matrix() -> Self {
        Self {
            accent: Color::Rgb(0, 255, 65),
            panel_bg: Color::Rgb(0, 0, 0),
            sidebar_bg: Color::Reset,
            active_row_bg: Color::Rgb(0, 59, 15),
            selection_bg: Color::Rgb(0, 90, 23),
            surface0: Color::Rgb(10, 31, 13),
            surface1: Color::Rgb(16, 48, 21),
            surface_dim: Color::Rgb(0, 0, 0),
            overlay0: Color::Rgb(15, 107, 36),
            overlay1: Color::Rgb(31, 154, 58),
            text: Color::Rgb(0, 255, 65),
            subtext0: Color::Rgb(0, 179, 44),
            mauve: Color::Rgb(57, 255, 20),
            green: Color::Rgb(0, 255, 65),
            yellow: Color::Rgb(168, 255, 96),
            red: Color::Rgb(255, 59, 59),
            blue: Color::Rgb(0, 201, 87),
            teal: Color::Rgb(0, 230, 118),
            peach: Color::Rgb(127, 255, 0),
        }
    }

    /// Procomm Plus for DOS: CGA blue, white text, yellow and cyan highlights.
    pub fn procomm() -> Self {
        Self {
            accent: Color::Rgb(255, 255, 85),
            panel_bg: Color::Rgb(0, 0, 170),
            sidebar_bg: Color::Reset,
            active_row_bg: Color::Rgb(0, 0, 212),
            selection_bg: Color::Rgb(0, 128, 128),
            surface0: Color::Rgb(26, 26, 170),
            surface1: Color::Rgb(51, 51, 187),
            surface_dim: Color::Rgb(0, 0, 96),
            overlay0: Color::Rgb(85, 85, 255),
            overlay1: Color::Rgb(170, 170, 170),
            text: Color::Rgb(255, 255, 255),
            subtext0: Color::Rgb(170, 170, 170),
            mauve: Color::Rgb(255, 85, 255),
            green: Color::Rgb(85, 255, 85),
            yellow: Color::Rgb(255, 255, 85),
            red: Color::Rgb(255, 85, 85),
            blue: Color::Rgb(85, 85, 255),
            teal: Color::Rgb(85, 255, 255),
            peach: Color::Rgb(255, 170, 0),
        }
    }

    /// Ambar: amber-phosphor monitor of the 80s, black background and amber text.
    pub fn ambar() -> Self {
        Self {
            accent: Color::Rgb(255, 176, 0),
            panel_bg: Color::Rgb(0, 0, 0),
            sidebar_bg: Color::Reset,
            active_row_bg: Color::Rgb(61, 40, 0),
            selection_bg: Color::Rgb(92, 60, 0),
            surface0: Color::Rgb(26, 17, 0),
            surface1: Color::Rgb(41, 27, 0),
            surface_dim: Color::Rgb(0, 0, 0),
            overlay0: Color::Rgb(128, 88, 0),
            overlay1: Color::Rgb(179, 123, 0),
            text: Color::Rgb(255, 176, 0),
            subtext0: Color::Rgb(204, 140, 0),
            mauve: Color::Rgb(255, 204, 102),
            green: Color::Rgb(255, 214, 64),
            yellow: Color::Rgb(255, 224, 120),
            red: Color::Rgb(255, 85, 0),
            blue: Color::Rgb(230, 150, 40),
            teal: Color::Rgb(255, 192, 64),
            peach: Color::Rgb(255, 140, 0),
        }
    }

    /// Miami: Vice City sunset. Deep violet #3B146B, purple #7B208F, magenta #C9349B,
    /// coral pink #F36A78, coral #F87572, orange #FF9B55 and warm yellow #FFB458.
    pub fn miami() -> Self {
        Self {
            accent: Color::Rgb(243, 106, 120),
            panel_bg: Color::Rgb(59, 20, 107),
            sidebar_bg: Color::Reset,
            active_row_bg: Color::Rgb(123, 32, 143),
            selection_bg: Color::Rgb(94, 26, 125),
            surface0: Color::Rgb(75, 24, 118),
            surface1: Color::Rgb(91, 30, 130),
            surface_dim: Color::Rgb(42, 12, 80),
            overlay0: Color::Rgb(201, 52, 155),
            overlay1: Color::Rgb(224, 132, 184),
            text: Color::Rgb(255, 228, 214),
            subtext0: Color::Rgb(248, 180, 170),
            mauve: Color::Rgb(226, 80, 176),
            green: Color::Rgb(110, 231, 183),
            yellow: Color::Rgb(255, 180, 88),
            red: Color::Rgb(255, 84, 112),
            blue: Color::Rgb(120, 170, 255),
            teal: Color::Rgb(64, 224, 208),
            peach: Color::Rgb(255, 155, 85),
        }
    }
}
