use std::ffi::CStr;
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Action {
    Open(String),
    Play,
    Pause,
    Resume,
    Seek(i32),
    Volume(u8),
    Wait,
    Stop,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ScriptError {
    pub line: usize,
    pub message: String,
}

impl std::fmt::Display for ScriptError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "line {}: {}", self.line, self.message)
    }
}

impl std::error::Error for ScriptError {}

pub fn parse(source: &str) -> Result<Vec<Action>, ScriptError> {
    let mut actions = Vec::new();
    for (index, raw_line) in source.lines().enumerate() {
        let line_number = index + 1;
        let line = raw_line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }

        let (command, argument) = line
            .split_once(char::is_whitespace)
            .map_or((line, ""), |(command, argument)| (command, argument.trim()));
        let action = match command {
            "open" => Action::Open(parse_quoted_path(argument, line_number)?),
            "play" if argument.is_empty() => Action::Play,
            "pause" if argument.is_empty() => Action::Pause,
            "resume" if argument.is_empty() => Action::Resume,
            "wait" if argument.is_empty() => Action::Wait,
            "stop" if argument.is_empty() => Action::Stop,
            "seek" => {
                let offset = argument.parse::<i32>().map_err(|_| ScriptError {
                    line: line_number,
                    message:
                        "seek expects a signed number of seconds, such as `seek 20` or `seek -10`"
                            .into(),
                })?;
                if !(-3600..=3600).contains(&offset) || offset % 10 != 0 {
                    return Err(ScriptError {
                        line: line_number,
                        message: "seek offset must be a 10-second step between -3600 and 3600"
                            .into(),
                    });
                }
                Action::Seek(offset)
            }
            "volume" => {
                let volume = argument.parse::<u8>().map_err(|_| ScriptError {
                    line: line_number,
                    message: "volume expects an integer from 0 to 100".into(),
                })?;
                if volume > 100 {
                    return Err(ScriptError {
                        line: line_number,
                        message: "volume must be between 0 and 100".into(),
                    });
                }
                Action::Volume(volume)
            }
            "play" | "pause" | "resume" | "wait" | "stop" => {
                return Err(ScriptError {
                    line: line_number,
                    message: format!("unexpected argument for `{command}`"),
                });
            }
            _ => {
                return Err(ScriptError {
                    line: line_number,
                    message: format!("unknown command `{command}`"),
                });
            }
        };
        actions.push(action);
    }
    Ok(actions)
}

fn parse_quoted_path(argument: &str, line: usize) -> Result<String, ScriptError> {
    let Some(inner) = argument
        .strip_prefix('"')
        .and_then(|value| value.strip_suffix('"'))
    else {
        return Err(ScriptError {
            line,
            message: "open expects a quoted media path".into(),
        });
    };
    if inner.is_empty() {
        return Err(ScriptError {
            line,
            message: "media path cannot be empty".into(),
        });
    }

    let mut output = String::with_capacity(inner.len());
    let mut characters = inner.chars();
    while let Some(character) = characters.next() {
        if character == '\\' {
            match characters.next() {
                Some('"') => output.push('"'),
                Some('\\') => output.push('\\'),
                Some(other) => {
                    output.push('\\');
                    output.push(other);
                }
                None => output.push('\\'),
            }
        } else {
            output.push(character);
        }
    }
    Ok(output)
}

pub fn run_script(path: &Path) -> Result<(), String> {
    if !path
        .extension()
        .and_then(|value| value.to_str())
        .is_some_and(|extension| extension.eq_ignore_ascii_case("powcurl"))
    {
        return Err("powcurl scripts must use the .powcurl extension".into());
    }

    let path = fs::canonicalize(path)
        .map_err(|error| format!("cannot open script '{}': {error}", path.display()))?;
    let source = fs::read_to_string(&path)
        .map_err(|error| format!("cannot read script '{}': {error}", path.display()))?;
    let actions = parse(&source).map_err(|error| error.to_string())?;
    let script_dir = path.parent().unwrap_or_else(|| Path::new("."));
    execute(&actions, script_dir)
}

fn execute(actions: &[Action], script_dir: &Path) -> Result<(), String> {
    let mut media_path: Option<PathBuf> = None;
    let mut volume = 50;
    let mut playing = false;
    let mut paused = false;

    for action in actions {
        match action {
            Action::Open(path) => {
                let requested = PathBuf::from(path);
                media_path = Some(if requested.is_absolute() {
                    requested
                } else {
                    script_dir.join(requested)
                });
            }
            Action::Play => {
                let path = media_path.as_deref().ok_or_else(|| {
                    "play requires an earlier `open \"path\"` command".to_string()
                })?;
                media_start(path, volume)?;
                playing = true;
                paused = false;
                println!("powcurl: playback window opened for '{}'", path.display());
            }
            Action::Pause => {
                if !playing {
                    return Err("pause requires active playback".into());
                }
                if !paused {
                    media_toggle_pause()?;
                    paused = true;
                }
            }
            Action::Resume => {
                if !playing {
                    return Err("resume requires active playback".into());
                }
                if paused {
                    media_toggle_pause()?;
                    paused = false;
                }
            }
            Action::Seek(offset) => {
                if !playing {
                    return Err("seek requires active playback".into());
                }
                media_seek(*offset)?;
            }
            Action::Volume(value) => {
                volume = *value;
                media_set_volume(volume)?;
            }
            Action::Wait => {
                if !playing {
                    return Err("wait requires active playback".into());
                }
                media_wait()?;
                playing = false;
                paused = false;
            }
            Action::Stop => {
                media_stop()?;
                playing = false;
                paused = false;
            }
        }
    }

    if !playing && actions.is_empty() {
        return Err("script contains no commands".into());
    }
    Ok(())
}

#[cfg(windows)]
mod player {
    use super::*;
    use std::os::windows::ffi::OsStrExt;

    unsafe extern "C" {
        fn operator_media_start(
            path: *const u16,
            volume: i32,
            status: *mut i8,
            capacity: usize,
        ) -> i32;
        fn operator_media_toggle_pause(status: *mut i8, capacity: usize) -> i32;
        fn operator_media_seek(seconds: i32, status: *mut i8, capacity: usize) -> i32;
        fn operator_media_set_volume(volume: i32, status: *mut i8, capacity: usize) -> i32;
        fn operator_media_wait(status: *mut i8, capacity: usize) -> i32;
        fn operator_media_stop(status: *mut i8, capacity: usize) -> i32;
    }

    fn call_backend(
        operation: &str,
        callback: impl FnOnce(*mut i8, usize) -> i32,
    ) -> Result<(), String> {
        let mut status = [0_i8; 512];
        let succeeded = callback(status.as_mut_ptr(), status.len()) != 0;
        let message = unsafe { CStr::from_ptr(status.as_ptr()) }
            .to_string_lossy()
            .into_owned();
        if succeeded {
            if !message.is_empty() {
                println!("powcurl: {message}");
            }
            Ok(())
        } else if message.is_empty() {
            Err(format!(
                "{operation} failed without a backend error message"
            ))
        } else {
            Err(format!("{operation} failed: {message}"))
        }
    }

    pub(super) fn start(path: &Path, volume: u8) -> Result<(), String> {
        let wide_path: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
        call_backend("play", |status, capacity| unsafe {
            operator_media_start(wide_path.as_ptr(), i32::from(volume), status, capacity)
        })
    }

    pub(super) fn toggle_pause() -> Result<(), String> {
        call_backend("pause", |status, capacity| unsafe {
            operator_media_toggle_pause(status, capacity)
        })
    }

    pub(super) fn seek(seconds: i32) -> Result<(), String> {
        call_backend("seek", |status, capacity| unsafe {
            operator_media_seek(seconds, status, capacity)
        })
    }

    pub(super) fn set_volume(volume: u8) -> Result<(), String> {
        call_backend("volume", |status, capacity| unsafe {
            operator_media_set_volume(i32::from(volume), status, capacity)
        })
    }

    pub(super) fn wait() -> Result<(), String> {
        call_backend("wait", |status, capacity| unsafe {
            operator_media_wait(status, capacity)
        })
    }

    pub(super) fn stop() -> Result<(), String> {
        call_backend("stop", |status, capacity| unsafe {
            operator_media_stop(status, capacity)
        })
    }
}

#[cfg(not(windows))]
mod player {
    use super::*;

    fn unsupported() -> Result<(), String> {
        Err("powcurl playback is currently supported only on Windows".into())
    }

    pub(super) fn start(_: &Path, _: u8) -> Result<(), String> {
        unsupported()
    }
    pub(super) fn toggle_pause() -> Result<(), String> {
        unsupported()
    }
    pub(super) fn seek(_: i32) -> Result<(), String> {
        unsupported()
    }
    pub(super) fn set_volume(_: u8) -> Result<(), String> {
        unsupported()
    }
    pub(super) fn wait() -> Result<(), String> {
        unsupported()
    }
    pub(super) fn stop() -> Result<(), String> {
        unsupported()
    }
}

fn media_start(path: &Path, volume: u8) -> Result<(), String> {
    player::start(path, volume)
}

fn media_toggle_pause() -> Result<(), String> {
    player::toggle_pause()
}

fn media_seek(seconds: i32) -> Result<(), String> {
    player::seek(seconds)
}

fn media_set_volume(volume: u8) -> Result<(), String> {
    player::set_volume(volume)
}

fn media_wait() -> Result<(), String> {
    player::wait()
}

fn media_stop() -> Result<(), String> {
    player::stop()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_media_control_script() {
        assert_eq!(
            parse(
            "# play a file\nopen \"Music/my song.mp3\"\nvolume 70\nplay\npause\nresume\nseek -20\nwait\n"
            )
            .unwrap(),
            vec![
                Action::Open("Music/my song.mp3".into()),
                Action::Volume(70),
                Action::Play,
                Action::Pause,
                Action::Resume,
                Action::Seek(-20),
                Action::Wait,
            ]
        );
    }

    #[test]
    fn parses_escaped_quotes_in_paths() {
        assert_eq!(
            parse(r#"open "Music/quote \"file\".mp3""#).unwrap(),
            vec![Action::Open("Music/quote \"file\".mp3".into())]
        );
    }

    #[test]
    fn reports_unknown_commands_with_line_number() {
        let error = parse("open \"song.wav\"\nlaunch").unwrap_err();
        assert_eq!(error.line, 2);
        assert!(error.message.contains("unknown command"));
    }

    #[test]
    fn rejects_unquoted_paths_and_invalid_values() {
        assert!(parse("open song.wav").is_err());
        assert!(parse("volume 101").is_err());
        assert!(parse("seek 3601").is_err());
        assert!(parse("seek 7").is_err());
    }

    #[test]
    fn requires_play_to_follow_open_at_runtime() {
        let actions = parse("play").unwrap();
        let result = execute(&actions, Path::new("."));
        assert!(result.unwrap_err().contains("earlier `open"));
    }
}
