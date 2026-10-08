# Fr3do Audio Extractor

Aplicación de escritorio en Python para descargar canciones y playlists de YouTube y SoundCloud, e importar canciones, álbumes y playlists de Spotify buscando versiones en YouTube en WAV o MP3 a 320 kbps. Opcionalmente separa el audio con Demucs en cuatro stems WAV: `vocals`, `drums`, `bass` y `other`.

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

Copia `main.py`, `sources.py`, `requirements.txt` y este `README.md` dentro de esa carpeta.

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

1. Elige la carpeta de salida con **EXPLORAR**.
2. Selecciona **WAV** o **MP3 320**. Convertir a 320 kbps no mejora la calidad original.
3. Activa **4-STEM** si quieres separar cada canción con Demucs.
4. Pega un enlace de YouTube, SoundCloud o Spotify y pulsa **EXTRAER**.
5. Revisa la lista, selecciona todas o algunas pistas y pulsa **Descargar selección**.

Los enlaces de video de YouTube que incluyan `list=` se analizan como playlist. Para descargar solo el video, usa su enlace sin ese parámetro. Las pistas privadas, retiradas o restringidas pueden omitirse o fallar.

Las playlists se guardan en una carpeta con su nombre. Cada pista conserva su índice original; las canciones repetidas tienen nombres distintos. En modo 4-STEM se crea una subcarpeta por canción con las cuatro pistas WAV. El WAV intermedio se elimina cuando la separación termina correctamente.

El progreso indica canción actual y total seleccionado. FFmpeg y Demucs muestran actividad durante su procesamiento. Si una canción falla, la aplicación continúa con las demás y muestra un resultado parcial. `fr3do-resultados.json` registra fuentes, archivos guardados y errores. No se sobrescriben carpetas ni archivos anteriores.

## 8. Conectar Spotify

Spotify aporta nombres y artistas; **el audio se obtiene desde YouTube**, nunca desde Spotify. No se garantiza que la coincidencia sea la misma versión. La vista previa muestra ambos títulos y un botón **Abrir** para revisar la fuente. Las coincidencias comienzan desmarcadas y requieren selección explícita.

1. Crea una app en https://developer.spotify.com/dashboard.
2. Registra exactamente `http://127.0.0.1:8888/callback` como Redirect URI.
3. Copia el **Client ID**, pulsa **CONFIGURAR SPOTIFY** e introdúcelo. No hace falta Client Secret.
4. Pega un enlace `https://open.spotify.com/playlist/...`, `/album/...` o `/track/...`.
5. Autoriza el acceso en el navegador del equipo donde ejecutas Fr3do.

También puedes definir el Client ID antes de ejecutar, en PowerShell:

```powershell
$env:SPOTIPY_CLIENT_ID = "tu_client_id"
python main.py
```

Se utiliza OAuth PKCE y los tokens permanecen en memoria durante la importación, sin archivos de credenciales. Una nueva importación puede requerir autorización nuevamente. El puerto local 8888 debe estar libre.

**Restricciones actuales de Spotify (2026):** en modo desarrollo, el dueño de la app debe tener Premium y el contenido de playlists solo se devuelve si el usuario conectado es dueño o colaborador. Los usuarios deben estar habilitados en la app. Una playlist pública de otra persona puede resultar inaccesible. Las pistas locales y episodios se omiten. La API puede limitar solicitudes.

Referencias oficiales:
- https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide
- https://developer.spotify.com/documentation/web-api/reference/get-playlists-items

## 9. Pruebas

```powershell
python -m unittest discover -s tests -v
```

Las pruebas verifican resolución y paginación con respuestas simuladas, continuidad ante errores y conservación de archivos. No requieren cuentas ni descargan música. Las descargas reales y la autorización de Spotify requieren una prueba en el equipo de destino.

## Solución de problemas

- **FFmpeg no está instalado o no aparece en PATH:** reinicia PowerShell/VS Code y ejecuta `ffmpeg -version`.
- **Demucs no se reconoce:** confirma que `.venv` está activado y ejecuta `python -m demucs --help`.
- **Demucs se queda sin memoria:** cierra programas pesados. La primera ejecución también descarga el modelo de separación.
- **YouTube rechaza la descarga:** actualiza yt-dlp con `python -m pip install -U yt-dlp`.
- **PowerShell bloquea Activate.ps1:** ejecuta `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` en esa misma ventana.

