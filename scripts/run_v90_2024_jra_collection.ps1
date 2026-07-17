param(
    [string]$Db = "data/db/analysis.sqlite",
    [string]$Log = ".workstate/logs/v90_2024_jra_collection.log"
)

$batches = @(
    @{ From = "2024-01-01"; To = "2024-01-15"; Courses = "nakayama,kyoto,kokura" },
    @{ From = "2024-01-16"; To = "2024-01-31"; Courses = "nakayama,kyoto,kokura" },
    @{ From = "2024-02-01"; To = "2024-02-15"; Courses = "tokyo,kyoto,hanshin,kokura" },
    @{ From = "2024-02-16"; To = "2024-02-29"; Courses = "tokyo,kyoto,hanshin,kokura" },
    @{ From = "2024-03-01"; To = "2024-03-15"; Courses = "nakayama,chukyo,hanshin" },
    @{ From = "2024-03-16"; To = "2024-03-31"; Courses = "nakayama,chukyo,hanshin" },
    @{ From = "2024-04-01"; To = "2024-04-15"; Courses = "fukushima,nakayama,hanshin" },
    @{ From = "2024-04-16"; To = "2024-04-30"; Courses = "fukushima,tokyo,kyoto" },
    @{ From = "2024-05-01"; To = "2024-05-15"; Courses = "niigata,tokyo,kyoto" },
    @{ From = "2024-05-16"; To = "2024-05-31"; Courses = "niigata,tokyo,kyoto" },
    @{ From = "2024-06-01"; To = "2024-06-15"; Courses = "tokyo,hanshin" },
    @{ From = "2024-06-16"; To = "2024-06-30"; Courses = "tokyo,hanshin,hakodate" },
    @{ From = "2024-07-01"; To = "2024-07-15"; Courses = "hakodate,fukushima,kokura" },
    @{ From = "2024-07-16"; To = "2024-07-31"; Courses = "hakodate,fukushima,kokura,sapporo" },
    @{ From = "2024-08-01"; To = "2024-08-15"; Courses = "sapporo,niigata" },
    @{ From = "2024-08-16"; To = "2024-08-31"; Courses = "sapporo,niigata" }
)

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Log) | Out-Null
foreach ($item in $batches) {
    $previous = -1
    for ($attempt = 1; $attempt -le 120; $attempt++) {
        $countCode = @"
import sqlite3
connection = sqlite3.connect(r'$Db')
print(connection.execute("select count(*) from race_results rr join races r on r.race_id=rr.race_id where r.race_date>=? and r.race_date<=?", ("$($item.From)", "$($item.To)")).fetchone()[0])
"@
        $count = (& rtk uv run python -X utf8 -c $countCode)
        if ($count -eq $previous) { break }
        $previous = [int]$count
        "$(Get-Date -Format o) $($item.From)..$($item.To) attempt=$attempt results=$count" | Tee-Object -FilePath $Log -Append
        & rtk uv run jra-srb collect-analysis --from-date $item.From --to-date $item.To --courses $item.Courses --db $Db --include-card --include-results --retries 1 --min-interval-seconds 3 --max-live-requests 10 --skip-existing 2>&1 | Tee-Object -FilePath $Log -Append
        if ($LASTEXITCODE -ne 0) { throw "collection failed: $($item.From)..$($item.To)" }
    }
    & rtk uv run jra-srb verify-analysis-joins --from-date $item.From --to-date $item.To --db $Db --sample-size 5 2>&1 | Tee-Object -FilePath $Log -Append
    if ($LASTEXITCODE -ne 0) { throw "join verification failed: $($item.From)..$($item.To)" }
}
