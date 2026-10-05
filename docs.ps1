# Wizard documentation kit, for you and for the Gemini CLI tasks (tasks\2x and 3x). Run it in the Wizard folder:
#   .\docs.ps1 check                         pywin32 and Office on this PC
#   .\docs.ps1 outlook-folders               your Outlook mail folders with item counts
#   .\docs.ps1 outlook-export --folder "Inbox/Projects" --since 2026-01-01 [--match launch GTM] [--max 500]
#   .\docs.ps1 extract                       convert everything in content\inbox to text (only new or changed files)
#   .\docs.ps1 status | next [--limit 25] | topics | coverage
#   .\docs.ps1 validate                      check content\ the way Wizard checks it at start-up
#   .\docs.ps1 quiz-check <page.html>        check a quiz page before emailing it
#   .\docs.ps1 quiz-answers [<file or folder>]   read answered quizzes (default: documents\quiz-answers)
# Everything runs on this PC: no network, no AI. Gemini CLI does the reading and writing; this does the converting,
# counting and checking.
$ErrorActionPreference = 'Stop'
$command = if ($args.Count) { [string]$args[0] } else { 'help' }
$rest = @($args | Select-Object -Skip 1 | ForEach-Object { [string]$_ })
$installDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$pointer = Join-Path $installDir 'current.json'
if (Test-Path -LiteralPath $pointer) {
    $current = Get-Content -LiteralPath $pointer -Raw | ConvertFrom-Json
    $python = $current.python; $release = $current.release
} elseif (Test-Path -LiteralPath (Join-Path $installDir 'run.py')) {
    $venv = Join-Path $installDir '.venv\Scripts\python.exe'   # development checkout
    $python = if (Test-Path -LiteralPath $venv) { $venv } else { 'python' }; $release = $installDir
} else {
    throw "No installed release in $installDir. Run .\setup.ps1 first."
}
$kit = Join-Path $release 'scripts\wizard_docs.py'
$content = Join-Path $installDir 'content'
$quizzes = Join-Path $installDir 'documents\quiz-questions'
$answers = Join-Path $installDir 'documents\quiz-answers'
switch ($command) {
    'validate' { & $python (Join-Path $release 'scripts\validate_content.py') $content; exit $LASTEXITCODE }
    { $_ -in @('extract', 'next', 'topics', 'coverage', 'outlook-export') } { $arguments = @($command, $content) + $rest; break }
    'status' { $arguments = @('status', $content, '--quizzes', $quizzes) + $rest; break }
    'quiz-check' { $arguments = @('quiz-check') + $rest + @('--content', $content); break }
    'quiz-answers' { if ($rest.Count -eq 0) { $rest = @($answers) }; $arguments = @('quiz-answers') + $rest + @('--quizzes', $quizzes); break }
    { $_ -in @('help', '-h', '--help', '/?') } { $arguments = @('--help'); break }
    default { $arguments = @($command) + $rest }
}
& $python $kit @arguments
exit $LASTEXITCODE
