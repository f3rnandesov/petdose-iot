# 🐾 PetDose — Dispensador Inteligente com Supervisão SaaS

![ESP32](https://img.shields.io/badge/Hardware-ESP32-blue?logo=espressif)
![Python](https://img.shields.io/badge/Dashboard-Python%2FNiceGUI-3776AB?logo=python)
![MQTT](https://img.shields.io/badge/Protocolo-MQTT-660066?logo=eclipse-mosquitto)
![Status](https://img.shields.io/badge/MVP-Conclu%C3%ADdo-brightgreen)

O **PetDose** é uma solução IoT baseada no conceito de Inovação Frugal, projetada para otimizar o processo de alimentação animal em ONGs, abrigos comunitários e serviços de hospedagem pet em São Luís - MA. 

Diferente de dispensadores convencionais, o PetDose utiliza sensorização dupla (Ultrassónica + Optoeletrónica) para validar a entrega real do alimento e detetar bloqueios mecânicos em tempo real, integrando-se a um modelo de negócio por assinatura (**SaaS**).

---

##  Arquitetura e Hardware

- **Microcontrolador:** ESP32-WROOM-32
- **Sensores:** 
  - Sensor Ultrassónico HC-SR04 (Nível do reservatório)
  - Módulo LDR (Confirmação de queda na calha / Deteção de obstrução)
- **Atuador:** Servomotor SG90 (Controlo da catraca)
- **Comunicação:** Wi-Fi 802.11 b/g/n e MQTT via Broker Public (HiveMQ/Mosquitto)

---

##  Camada de Inteligência (Dashboard SaaS)

A interface administrativa foi desenvolvida em **Python (NiceGUI)** e provê:
- **Painel de Métricas (KPIs):** Distância residual do reservatório e contagem diária de refeições.
- **Supervisão Ativa:** Alertas visuais instantâneos em caso de falha de dispersão ou reservatório vazio.
- **Controlo Remoto:** Acionamento sob demanda do dispensador via MQTT.
- **Auditoria de Eventos:** Histórico em tempo real para comprovação de alimentação remota.

---

##  Montagem na Bancada (ESP32 real)

### Ligações

| Componente | Pino do componente | Ligar em |
|---|---|---|
| HC-SR04 | VCC | 5V (VIN do ESP32) |
| HC-SR04 | GND | GND |
| HC-SR04 | TRIG | GPIO 5 |
| HC-SR04 | ECHO | GPIO 19 **via divisor de tensão** (ver abaixo) |
| Servo SG90 | Marrom (GND) | GND |
| Servo SG90 | Vermelho (+) | 5V (de preferência fonte externa) |
| Servo SG90 | Laranja (sinal) | GPIO 18 |
| Botão | um terminal | GPIO 4 |
| Botão | outro terminal | GND |

**Divisor de tensão no ECHO:** o HC-SR04 devolve 5 V e o ESP32 aceita no máximo 3,3 V.
Ligue `ECHO → resistor 1 kΩ → GPIO 19` e `GPIO 19 → resistor 2 kΩ → GND`.
Sem isso o sensor pode funcionar por um tempo, mas danifica o pino do ESP32.

**Alimentação do servo:** o servo puxa picos de corrente que podem reiniciar o ESP32
(sintoma: o ESP reinicia quando a comporta abre). Use uma fonte 5 V separada ou um
capacitor de 470–1000 µF entre 5V e GND do servo. **O GND da fonte e do ESP32 devem estar unidos.**

### Configuração do firmware (`firmware/sketch.ino`)

1. Preencha `ssid` e `password` com a rede da bancada. Recomendação: roteador do celular,
   pois redes institucionais costumam bloquear a porta 1883 do MQTT.
2. Instale na Arduino IDE as bibliotecas **PubSubClient**, **ESP32Servo** e **ArduinoJson**.

### Calibração do reservatório

1. Abra o Monitor Serial (115200). A cada 5 s aparece `[calibracao] distancia = XX cm`.
2. Com o pote **vazio**, anote a distância → `DIST_VAZIO_CM`.
3. Encha o pote até o máximo, anote a distância → `DIST_CHEIO_CM`
   (o HC-SR04 não mede bem abaixo de ~3 cm; deixe essa folga entre o sensor e a ração).
4. Pese quanto de ração coube → `CAPACIDADE_SILO_G`.

### Calibração da dosagem

1. Coloque um pote sobre uma balança de cozinha embaixo da saída.
2. Configure no dashboard um pet com porção de 250 g e mande servir.
3. Pese o que caiu: `VAZAO_G_POR_S = 25.0 × (peso real ÷ 250)`.
4. Repita 2–3 vezes e use a média. Ajuste `SERVO_ABERTO`/`SERVO_FECHADO` se a comporta
   não abrir ou fechar totalmente.

---

##  Como Executar o Projeto

### 1. Simulação do Hardware (Wokwi)
- Acesse o projeto no Wokwi: https://wokwi.com/projects/481051231945435137
- Certifique-se de que a biblioteca `ESP32Servo` e `PubSubClient` estão configuradas.
- Inicie a simulação para conectar o dispositivo à rede e ao broker MQTT.

### 2. Execução do Dashboard Local
```bash
# Clone o repositório
git clone [https://github.com/f3rnandesov/petdose-iot.git](https://github.com/f3rnandesov/petdose-iot.git)
cd petdose-iot

# Crie e ative o ambiente virtual
python3 -m venv .venv
source .venv/bin/activate

# Instale as dependências
pip install -r requeriments.txt

# Execute a aplicação
python3 dashboard/dashbord_wokwi.py
