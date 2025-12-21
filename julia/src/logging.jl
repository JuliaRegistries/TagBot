"""
Logging utilities for TagBot.
"""

# ============================================================================
# GitHub Actions Log Formatting
# ============================================================================

"""
    ActionLogHandler <: AbstractLogger

A logger that formats output for GitHub Actions.
"""
struct ActionLogHandler <: AbstractLogger
    min_level::LogLevel
end

ActionLogHandler() = ActionLogHandler(Logging.Info)

Logging.min_enabled_level(logger::ActionLogHandler) = logger.min_level
Logging.shouldlog(logger::ActionLogHandler, level, _module, group, id) = level >= logger.min_level
Logging.catch_exceptions(logger::ActionLogHandler) = true

function Logging.handle_message(logger::ActionLogHandler, level, message, _module, group, id, file, line; kwargs...)
    # Format message for GitHub Actions
    msg = string(message)
    for (k, v) in kwargs
        msg *= " $k=$v"
    end

    if level == Logging.Debug
        # GitHub Actions debug format
        msg = replace(msg, "%" => "%25", "\n" => "%0A", "\r" => "%0D")
        println("::debug ::$msg")
    elseif level == Logging.Warn
        msg = replace(msg, "%" => "%25", "\n" => "%0A", "\r" => "%0D")
        println("::warning ::$msg")
    elseif level == Logging.Error
        msg = replace(msg, "%" => "%25", "\n" => "%0A", "\r" => "%0D")
        println("::error ::$msg")
    else
        # Info level - just print normally
        println(msg)
    end
end

"""
    FallbackLogHandler <: AbstractLogger

A fallback logger for non-Actions environments.
"""
struct FallbackLogHandler <: AbstractLogger
    min_level::LogLevel
end

FallbackLogHandler() = FallbackLogHandler(Logging.Info)

Logging.min_enabled_level(logger::FallbackLogHandler) = logger.min_level
Logging.shouldlog(logger::FallbackLogHandler, level, _module, group, id) = level >= logger.min_level
Logging.catch_exceptions(logger::FallbackLogHandler) = true

function Logging.handle_message(logger::FallbackLogHandler, level, message, _module, group, id, file, line; kwargs...)
    timestamp = Dates.format(now(), "HH:MM:SS")
    level_str = uppercase(string(level))
    msg = string(message)
    for (k, v) in kwargs
        msg *= " $k=$v"
    end
    println("$timestamp | $level_str | $msg")
end

"""
    setup_logging()

Set up the appropriate logger based on the environment.
"""
function setup_logging()
    if get(ENV, "GITHUB_ACTIONS", "") == "true"
        global_logger(ActionLogHandler())
    else
        global_logger(FallbackLogHandler())
    end
end

# ============================================================================
# Sanitization
# ============================================================================

"""
    sanitize(text::String, token::String)

Remove sensitive tokens from text.
"""
function sanitize(text::AbstractString, token::AbstractString)
    isempty(token) ? text : replace(text, token => "***")
end
