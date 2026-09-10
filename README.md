# Fr3do Audio Extractor

Aplicación de escritorio en Python para extraer audio de videos de YouTube en WAV o MP3 a 320 kbps. Opcionalmente separa el audio con Demucs en cuatro stems WAV: `vocals`, `drums`, `bass` y `other`.

> Utiliza la aplicación únicamente con contenido propio, con licencia o para el que tengas autorización. Respeta los derechos de autor y los términos aplicables.

## 1. Requisitos recomendados

- Windows 10 u 11 de 64 bits.
- Python 3.11 de 64 bits.
- VS Code con la extensión oficial **Python**.
- FFmpeg disponible en `PATH`.
- Al menos 8 GB de RAM para Demucs. La descarga y conversión funcionan sin GPU; la separación en CPU tarda más.

## 2. Crear el proyecto desde PowerShell

Abre PowerShell y ejecuta:

```powershell
New-Item -ItemType Directory -Force "C:\Users\PROV_ARF\Documents\App 2\Fr3do"
Set-Location "C:\Users\PROV_ARF\Documents\App 2\Fr3do"
```

Copia `main.py`, `requirements.txt` y este `README.md` dentro de esa carpeta.

## 3. Crear y activar el entorno virtual

```powershell
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
```

Si `py -3.11` no existe, instala Python 3.11 desde python.org marcando **Add Python to PATH**.

## 4. Instalar FFmpeg

Opción recomendada con `winget`:

```powershell
winget install --id Gyan.FFmpeg --exact
```

Cierra y vuelve a abrir PowerShell después de instalarlo. Comprueba:

```powershell
ffmpeg -version
```

Si `ffmpeg` no se reconoce, reinicia VS Code o Windows para refrescar `PATH`.

## 5. Instalar las dependencias

Con el entorno virtual activado:

```powershell
pip install -r requirements.txt
```

Demucs instalará PyTorch y puede ocupar bastante espacio. Si la instalación automática de PyTorch falla y usarás solo CPU:

```powershell
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

Verifica los componentes:

```powershell
python -c "import customtkinter, yt_dlp; print('GUI y descarga OK')"
python -m demucs --help
ffmpeg -version
```

## 6. Ejecutar desde VS Code

```powershell
code "C:\Users\PROV_ARF\Documents\App 2\Fr3do"
```

En VS Code:

1. Presiona `Ctrl+Shift+P`.
2. Selecciona **Python: Select Interpreter**.
3. Elige `.venv\Scripts\python.exe`.
4. Abre `main.py` y presiona **Run Python File**, o ejecuta:

```powershell
python main.py
```

## 7. Uso

1. Elige la carpeta de salida con **Examinar**.
2. Selecciona obligatoriamente **WAV** o **MP3 · 320 kbps**.
3. Marca **Separar Stems** si necesitas voces, batería, bajo y otros.
4. Pega una URL de YouTube y pulsa **Descargar audio**.
5. Revisa el progreso en la consola inferior.

En una descarga básica, el audio final se guarda directamente en la carpeta elegida. Si activas Demucs, se crea `Carpeta elegida\Nombre de canción\`; dentro quedan exclusivamente `01 - Vocals.wav`, `02 - Drums.wav`, `03 - Bass.wav` y `04 - Other.wav`. El audio completo usado durante la separación se elimina al terminar correctamente.

La barra principal muestra porcentaje, velocidad y tiempo restante. Durante la conversión y separación cambia a modo de actividad. El log queda reservado para hitos, rutas y errores.

La descarga utiliza hasta 8 fragmentos concurrentes, un buffer de red de 1 MiB y bloques HTTP de 10 MiB cuando el servidor de YouTube admite esas modalidades. Los trabajos pesados se ejecutan mediante un `ThreadPoolExecutor`, fuera del hilo de la interfaz.

En modo stems, la aplicación convierte primero el stream a WAV aunque se haya seleccionado MP3. Esto evita fallos de decodificación de MP3 en Demucs sobre Windows; el archivo intermedio se elimina después de producir correctamente los cuatro stems.

Al terminar correctamente, la URL se limpia, la carpeta seleccionada se conserva y la interfaz queda lista para otra descarga.

## Solución de problemas

- **FFmpeg no está instalado o no aparece en PATH:** reinicia PowerShell/VS Code y ejecuta `ffmpeg -version`.
- **Demucs no se reconoce:** confirma que `.venv` está activado y ejecuta `python -m demucs --help`.
- **Demucs se queda sin memoria:** cierra programas pesados. La primera ejecución también descarga el modelo de separación.
- **YouTube rechaza la descarga:** actualiza yt-dlp con `python -m pip install -U yt-dlp`.
- **PowerShell bloquea Activate.ps1:** ejecuta `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` en esa misma ventana.
