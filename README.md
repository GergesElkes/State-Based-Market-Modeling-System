# 📊 Financial Market State Transition Analysis Dashboard

An interactive desktop application for analyzing financial market behavior using a custom **13-state model**, built with PyQt6.
This project processes high-frequency price data (XAUUSD) and visualizes price movement, state transitions, and timing regimes in a synchronized dashboard.

---

## 🚀 Overview

This application transforms raw tick-level financial data into structured **market states**, enabling deeper insight into:

* Market behavior patterns
* State transition probabilities
* Timing regimes (EARLY / CLOCK / LATE)
* Price dynamics over time

It combines **data analysis + visualization + modeling** into a single interactive tool.

---

## 🧠 Key Features

### 📈 Price Chart

* Real-time synchronized price visualization
* State-colored background bands
* Interactive cursor tracking

### ⏱ Tick Speed Analysis

* Visualizes time between ticks
* Classifies regimes:

  * EARLY (< 0.495s)
  * CLOCK (0.495–0.505s)
  * LATE (> 0.505s)

### 🧩 13-State Puzzle Board

* Custom state machine visualization
* Clickable states to jump to real data examples
* Shows:

  * State frequency
  * Average speed
  * Dominant regime
  * Transition probabilities

### 🔄 State Transition Analysis

* Tracks most likely next states
* Displays top transition paths with probabilities

### 🎮 Interactive Controls

* Play / pause time progression
* Zoom in/out on data window
* Slider navigation across dataset
* Jump to nearest state occurrence

---

## 🏗️ Project Structure

```
project/
├── main.py
├── requirements.txt
├── out.csv
├── last_400k_prices.csv
├── README.md
```

---

## 📂 Data Input

The application supports two types of CSV formats:

### 1. Raw Tick Data

Required columns:

* `price`
* `timestamp`

### 2. Labeled Data

Required columns:

* `current_state_id`
* `current_state_name`
* `tick_speed`
* `regime`

### 3. Hybrid (Recommended)

Includes both raw + labeled fields for best accuracy.

---

## ⚙️ Installation

### 1. Clone repository

```bash
git clone https://github.com/yourusername/project.git
cd project
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

---

## ▶️ Usage

### Run application:

```bash
python main.py
```

### Optional arguments:

```bash
python main.py --csv out.csv --raw last_400k_prices.csv
```

### Smoke test (headless):

```bash
python main.py --smoke-test
```

---

## 🧪 How It Works

### 1. State Encoding

Each price movement is converted into a **3-value comparison tuple**, then mapped into one of 13 states.

### 2. Regime Classification

Tick speed determines regime:

* EARLY → fast market
* CLOCK → stable timing
* LATE → slow market

### 3. Transition Modeling

The system tracks:

* Frequency of each state
* Probabilities of transitions between states

### 4. Visualization Engine

Custom rendering using PyQt6:

* No external plotting libraries
* Fully synchronized multi-panel display

---

## 📊 Example Insights

* Identify dominant market regimes per state
* Detect recurring transition patterns
* Analyze volatility through tick speed
* Explore clustering of similar behaviors

---

## 🧱 Technologies Used

* Python
* PyQt6 (GUI framework)
* CSV data processing
* Custom rendering (QPainter)

---

## 🎯 Use Cases

* Financial data exploration
* Quantitative analysis experiments
* Market behavior modeling
* Data visualization portfolio project

---

## ⚠️ Limitations

* No predictive model (yet)
* No backtesting engine
* Depends on input data quality
* Designed for exploration, not trading execution

---

## 🚧 Future Improvements

* Add prediction layer (next state forecasting)
* Export analytics results to CSV
* Integrate machine learning models
* Add real-time data streaming
* Improve performance for large datasets

---

## 📸 Screenshots

### 🖥 Main Dashboard
![Main UI](Capture3.PNG)

---

## 👤 Author

Gerges Elkes
GitHub: https://github.com/GergesElkes
