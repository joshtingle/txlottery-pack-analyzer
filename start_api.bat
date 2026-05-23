@echo off
cd /d %~dp0
set TXLOTTERY_SERVER=jtdc-sqlsrvr.cmhhlofylcq6.us-east-1.rds.amazonaws.com
set TXLOTTERY_DB=tx_lottery
set TXLOTTERY_UID=tx_lottery_svc
set TXLOTTERY_PWD=%1
uvicorn api:app --reload --port 8000
