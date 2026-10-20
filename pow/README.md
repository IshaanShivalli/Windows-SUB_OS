# POW — Polyglot Operator Workflow

```pow
let NAME=Operator
use operator: var.get SYS.OS
use powershell: Get-Date
pipe powershell: Get-Process | bash: grep python
import common.pow
```

Run a file with `pow file.pow` or `pow.exec file.pow` from Operator Shell.
