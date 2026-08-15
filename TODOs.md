# 功能性需求
1. ~~script for exporting roster, bid file~~ ✅ `/api/export/rosters.*`, `/api/export/bid-template`
2. ~~handle injury with replacement? Or just use SQL~~ ✅ `InjuryAdjustmentService` + `/api/admin/injuries`
3. ~~script with "dry-run" for testing~~ ✅ `?dry_run=true` on auction resolve / gameweek finalize / all bulk imports
4. 双线模式（联赛+杯赛）资格分离 ✅ `cup` 配置 + `domain/competition.py`（见 DESIGN.md §9）

# 可读性需求

## Configuration

1. 将所有的enum汇总为一个README.md中的部分
2. 