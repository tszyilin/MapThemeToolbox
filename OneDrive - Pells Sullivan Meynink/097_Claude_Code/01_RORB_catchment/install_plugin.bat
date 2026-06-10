@echo off
:: Installs rorb_catg_builder into the QGIS user plugins folder via a directory junction (no copy needed).
:: Run this once, then enable the plugin in QGIS Plugin Manager.

set PLUGIN_NAME=rorb_catg_builder
set SRC=%~dp0%PLUGIN_NAME%

:: Try QGIS 3.x default profile location
set QGIS_PLUGINS=%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins

if not exist "%QGIS_PLUGINS%" (
    echo Could not find QGIS plugins folder at:
    echo   %QGIS_PLUGINS%
    echo Please create it or copy the folder manually.
    pause
    exit /b 1
)

if exist "%QGIS_PLUGINS%\%PLUGIN_NAME%" (
    echo Removing existing link / folder…
    rmdir "%QGIS_PLUGINS%\%PLUGIN_NAME%"
)

mklink /J "%QGIS_PLUGINS%\%PLUGIN_NAME%" "%SRC%"
echo.
echo Plugin linked to:
echo   %QGIS_PLUGINS%\%PLUGIN_NAME%
echo.
echo Now open QGIS, go to Plugins ^> Manage and Install Plugins,
echo find "RORB Catchment Builder" and enable it.
pause
