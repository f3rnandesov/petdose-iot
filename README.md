# 🐾 PetDose — Dispensador Inteligente com Supervisão SaaS

![ESP32](https://img.shields.io/badge/Hardware-ESP32-blue?logo=espressif)
![Python](https://img.shields.io/badge/Dashboard-Python%2FNiceGUI-3776AB?logo=python)
![MQTT](https://img.shields.io/badge/Protocolo-MQTT-660066?logo=eclipse-mosquitto)
![Status](https://img.shields.io/badge/MVP-Conclu%C3%ADdo-brightgreen)

O **PetDose** é uma solução IoT baseada no conceito de **Inovação Frugal**, projetada para otimizar o processo de alimentação animal em ONGs, abrigos comunitários e serviços de hospedagem pet em São Luís - MA. 

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

##  Como Executar o Projeto

### 1. Simulação do Hardware (Wokwi)
- Acesse o projeto no Wokwi: `[Inserir Link da Simulação do Wokwi Aqui]`
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
pip install -r requirements.txt

# Execute a aplicação
python3 dashboard/main.py