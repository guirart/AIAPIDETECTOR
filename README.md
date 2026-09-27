# Monitor de EPI (protótipo)

Analisa o vídeo da câmera, detecta pessoas **sem capacete** e/ou **sem colete refletivo**,
dispara alerta (som + aviso na tela), guarda uma foto de evidência e registra tudo em um banco local.
Roda em um PC comum, sem placa de vídeo.

```
Câmera (webcam / RTSP / vídeo) → YOLO (detecção) → Regras (tempo mínimo, repetição) → Alerta + Registro → Relatório
```

## Arquivos

| Arquivo | Função |
|---|---|
| `config.yaml` | Tudo que se ajusta: câmera, EPIs obrigatórios, tempos, sensibilidade |
| `monitor.py` | Programa principal (janela do OpenCV) |
| `painel.py` + `painel/` | Tela web no estilo do Replay Vôlei |
| `regras.py` | Lógica de "essa pessoa está sem EPI?" |
| `registro.py` | Salva infrações (SQLite) e fotos em `registros/AAAA-MM-DD/` |
| `alertas.py` | Bipe + mensagem no console |
| `segredos.py` | Lê senhas/chaves das variáveis do Windows (nunca de arquivo) |
| `relatorio.py` | Gera `registros/relatorio.html` com totais, gráfico por hora e fotos |
| `detector_roboflow.py` | Detecção pelo workflow do Roboflow + rastreamento local |
| `workflows/epi_workflow.json` | Definição do workflow (modelo `construction-site-safety/27`) |
| `treinar.py` | Treina o modelo de EPI |
| `teste_regras.py` | Testes da lógica |

## Instalação (uma vez)

Precisa de Python 3.10+. Dê dois cliques em `instalar.bat`, ou rode manualmente:

```bash
py -m venv .venv
.venv\Scripts\python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
.venv\Scripts\python -m pip install -r requirements.txt
```

## Modelo

Há dois motores de detecção (`modelo.motor` no `config.yaml`):

### Opção A: workflow Roboflow (padrão, não precisa treinar)

Usa o modelo público `construction-site-safety/27` por meio do workflow em
[`workflows/epi_workflow.json`](workflows/epi_workflow.json), executado na nuvem do Roboflow.

1. Pegue sua chave em **app.roboflow.com → Settings → API Keys** (Private API Key).
2. No PowerShell: `setx ROBOFLOW_API_KEY "sua_chave"` e abra um terminal novo.
3. Rode `iniciar_monitor.bat`.

Limitações: precisa de internet, cada análise leva ~0,5–1 s (o vídeo fica mais "travado"),
consome créditos do plano do Roboflow e **as imagens da câmera são enviadas para a nuvem do Roboflow**
(considere isso na LGPD). Para produção, prefira a opção B.

### Opção B: modelo local (`motor: "local"`)

O sistema usa um modelo YOLO treinado para EPI, salvo em `modelos/epi.pt`.
O mapeamento de classes do `config.yaml` já está pronto para o dataset público
**Construction Site Safety** (classes `Person`, `Hardhat`, `NO-Hardhat`, `Safety Vest`, `NO-Safety Vest`...).

### Treinar grátis no Google Colab (recomendado, usa GPU)

1. Baixe um dataset de EPI em formato **YOLOv8/YOLO11** no [Roboflow Universe](https://universe.roboflow.com)
   (busque por "construction site safety" ou "ppe detection") ou use fotos da própria empresa.
2. Em [colab.research.google.com](https://colab.research.google.com), mude o ambiente para **GPU T4**, envie o `.zip` do dataset e rode:
   ```python
   !pip install ultralytics
   !unzip -q dataset.zip -d epi
   from ultralytics import YOLO
   YOLO("yolo11n.pt").train(data="epi/data.yaml", epochs=60, imgsz=640)
   ```
3. Baixe `runs/detect/train/weights/best.pt` e salve como `modelos/epi.pt`.

### Treinar no próprio PC (lento sem GPU)

```bash
.venv\Scripts\python treinar.py --dados caminho\do\dataset\data.yaml --epocas 30
```

> Se o seu modelo usar outros nomes de classe, ajuste `modelo.classes` no `config.yaml`.
> Ao iniciar, o monitor imprime quais classes reconheceu.

**Dica de precisão:** o melhor resultado vem de treinar (ou refinar) com imagens das **suas câmeras**,
no ângulo e iluminação reais. Umas 200–500 fotos anotadas já fazem muita diferença.

## Uso

```bash
.venv\Scripts\python monitor.py                          # usa o config.yaml
.venv\Scripts\python monitor.py --fonte 0                # webcam
.venv\Scripts\python monitor.py --fonte videos\obra.mp4  # vídeo gravado
.venv\Scripts\python relatorio.py --dias 7               # relatório da semana
```

Ou dê dois cliques em `iniciar_monitor.bat` / `abrir_relatorio.bat`. Na janela: **Q** ou **Esc** fecha.

### Tela web (recomendado)

Dois cliques em `iniciar_painel.bat` (ou `python painel.py`) abre **http://localhost:8080** com:
placar (pessoas, sem EPI, infrações do dia), faixa de status (verde / amarelo / vermelho no alerta),
vídeo ao vivo com as detecções e a lista de infrações com foto, filtrável por período.
Para abrir de outro PC ou celular na rede, mude `painel.host` para `"0.0.0.0"` no `config.yaml`
(a tela não tem senha — só em rede confiável).

### Câmeras Tapo (TP-Link)

O programa **não usa a conta Tapo na nuvem** (a TP-Link não libera o vídeo da nuvem para outros
programas). Ele recebe o vídeo **direto de cada câmera, pela rede local (RTSP)**. O PC precisa estar
na **mesma rede** (mesmo roteador/Wi-Fi) que as câmeras.

1. **Criar a conta da câmera** (uma vez, vale para todas se usar os mesmos dados): no app Tapo, abra a
   câmera → ⚙️ **Configurações** → **Configurações avançadas** → **Conta da câmera** → crie usuário e senha.
   *Não é* o login da sua conta Tapo.
2. **Descobrir o IP**: no app, câmera → ⚙️ → **Informações do dispositivo** → **Endereço IP**.
   Dica: no roteador, fixe esse IP (reserva de DHCP) para ele não mudar.
3. **Guardar usuário e senha no Windows** (PowerShell):
   ```
   setx TAPO_USUARIO "usuario_da_camera"
   setx TAPO_SENHA "senha_da_camera"
   ```
4. **No `config.yaml`**, em `cameras:`, troque o IP de cada Tapo e mude `ativa: false` para `true`.
   Use `stream1` (alta resolução) ou `stream2` (mais leve).
5. Teste antes no VLC: *Mídia → Abrir fluxo de rede* →
   `rtsp://usuario:senha@IP:554/stream1`.

Observações: modelos Tapo **a bateria** (ex.: C400, C420, D230) geralmente **não têm RTSP**.
Algumas câmeras aceitam no máximo 2 conexões RTSP ao mesmo tempo (VLC + monitor contam como 2).
Com o Roboflow, **cada câmera** gasta créditos separadamente — com várias câmeras, prefira o modelo local.

### Outras câmeras IP

Coloque o link RTSP na `fonte` da câmera. Formatos comuns:

- Intelbras / Dahua: `rtsp://usuario:senha@IP:554/cam/realmonitor?channel=1&subtype=0`
- Hikvision: `rtsp://usuario:senha@IP:554/Streaming/Channels/101`

Teste o link antes no VLC (Mídia → Abrir fluxo de rede). Se a câmera cair, o monitor tenta reconectar sozinho.

## Como a decisão é feita

- Capacete conta só se estiver na **parte de cima** da pessoa (capacete na mão não vale).
- Colete conta se estiver na região do **tronco**.
- Se o modelo detectar explicitamente "sem capacete"/"sem colete", isso prevalece.
- Só vira infração depois de `tempo_minimo_s` segundos seguidos (padrão 2s), para evitar alarme falso.
- A mesma pessoa não é registrada de novo antes de `intervalo_repeticao_s` (padrão 60s).

## LGPD

O protótipo **não identifica** quem é a pessoa: registra só câmera, horário, EPI faltando e a foto.
O número `#` é apenas um rastreamento temporário no vídeo. Mesmo assim, as fotos são dados pessoais:
informe os funcionários sobre o monitoramento, limite quem acessa a pasta `registros/`
e defina por quanto tempo as fotos serão guardadas.
