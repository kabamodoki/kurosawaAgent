@echo off
rem ==================================================================
rem  SSM port forwarding:  this PC 127.0.0.1:8000  ->  EC2 127.0.0.1:8000
rem  Edit INSTANCE_ID below before the first run (see setup-guide 11-1).
rem ==================================================================
set INSTANCE_ID=i-0123456789abcdef0
set PROFILE=kq-chat
set REGION=ap-northeast-1
set LOCAL_PORT=8000
rem ==================================================================

where aws >nul 2>nul
if errorlevel 1 (
  echo [error] AWS CLI was not found. Install AWS CLI v2, then open a new window.
  pause
  exit /b 1
)
where session-manager-plugin >nul 2>nul
if errorlevel 1 (
  echo [error] Session Manager plugin was not found. Install it, then open a new window.
  pause
  exit /b 1
)

echo Starting port forwarding to %INSTANCE_ID% (profile %PROFILE%, region %REGION%) ...
echo Keep this window open while you use the chat. Press Ctrl+C to stop.
aws ssm start-session --profile %PROFILE% --region %REGION% --target %INSTANCE_ID% --document-name AWS-StartPortForwardingSession --parameters portNumber=8000,localPortNumber=%LOCAL_PORT%
pause
