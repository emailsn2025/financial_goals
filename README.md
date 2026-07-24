# Net Worth & Goal Planner

A personal financial planning tool that projects inflated expenses, tracks goals, models asset growth, and dynamically allocates your portfolio against upcoming financial milestones.

## Features

- **Expense Tracker** — Itemized monthly expenses, each with its own inflation rate, projected over time
- **Goal Planner** — Define life goals with target costs and timelines, see inflation-adjusted future costs
- **Asset Portfolio** — Track holdings across 5 asset classes with individual growth projections
- **FIFO Goal Allocation** — Automatically maps projected portfolio growth against goals in chronological order
- **Smart Recommendations** — Shortfall alerts, inflation warnings, diversification checks, emergency fund guidance

## Run Locally

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the app
streamlit run app.py
```

Opens at `http://localhost:8501` in your browser.

## Deploy Free on Streamlit Community Cloud

### Step-by-step:

1. **Create a GitHub account** (if you don't have one) at [github.com](https://github.com)

2. **Create a new repository**
   - Go to [github.com/new](https://github.com/new)
   - Name it something like `financial-planner`
   - Set it to **Public** (required for the free tier)
   - Click **Create repository**

3. **Upload your files**
   - On your new repo page, click **"uploading an existing file"**
   - Drag in all 3 files: `app.py`, `requirements.txt`, `README.md`
   - Click **Commit changes**

4. **Deploy on Streamlit Cloud**
   - Go to [share.streamlit.io](https://share.streamlit.io)
   - Sign in with your GitHub account
   - Click **"New app"**
   - Select your repository, branch (`main`), and main file (`app.py`)
   - Click **Deploy**

5. **Share your link**
   - Your app will be live at `https://your-app-name.streamlit.app`
   - Share this URL with anyone — they can use it from any browser

### That's it! Your app updates automatically whenever you push changes to GitHub.

## How It Works

### Goal Allocation Logic (FIFO)
1. Goals are sorted by target year (earliest first)
2. Your full portfolio is projected to the first goal's year
3. If portfolio covers the goal, the excess cascades to goal #2
4. This repeats for each subsequent goal
5. Each goal shows a funding percentage and status

### Recommendations Engine
The app generates up to 5 actionable insights:
- **Shortfall SIP** — monthly savings needed to close funding gaps
- **Inflation Warning** — flags assets returning below your inflation rate
- **Horizon Matching** — suggests de-risking equity before near-term goals
- **Diversification** — alerts if any asset class exceeds 60% of portfolio
- **Emergency Fund** — checks if you have 6 months of expenses in liquid assets
