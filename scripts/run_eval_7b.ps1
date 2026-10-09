$qs = @(
 "How does Flask create the request context?",
 "Where are URL rules added?",
 "How are blueprints registered on an app?",
 "How is the session loaded from the cookie?",
 "Where is jsonify defined?",
 "How does a template get rendered?",
 "How is configuration loaded from an environment variable?",
 "How does Flask handle an error raised in a view?"
)
$i = 1
foreach ($q in $qs) {
  Write-Host "Running Q$i ..."
  python cli.py .repos\flask -q $q *>&1 | Out-File -Encoding utf8 "q${i}_7b.txt"
  $i++
}
