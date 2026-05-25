from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
import os
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="MT5 to Notion Webhook")

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
NOTION_VERSION = "2022-06-28"

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_USER_ID = os.getenv("LINE_USER_ID")


class TradePayload(BaseModel):
    event: str
    ticket: int
    symbol: str
    direction: Optional[str] = None
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    stop_loss: Optional[float] = None
    lot_size: Optional[float] = None
    profit_loss: Optional[float] = None
    result: Optional[str] = None
    open_time: Optional[str] = None
    close_time: Optional[str] = None


def notion_headers():
    if not NOTION_TOKEN:
        raise HTTPException(status_code=500, detail="NOTION_TOKEN is missing")

    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def line_headers():
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return None

    return {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def find_notion_page_by_ticket(ticket: int):

    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"

    payload = {
        "filter": {
            "property": "Ticket",
            "number": {
                "equals": ticket
            }
        }
    }

    response = requests.post(
        url,
        headers=notion_headers(),
        json=payload,
        timeout=15
    )

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=response.text
        )

    results = response.json().get("results", [])

    if not results:
        return None

    return results[0]["id"]


def build_create_properties(data: TradePayload):

    today = datetime.now().strftime("%Y-%m-%d")
    open_time = data.open_time or datetime.now().strftime("%H:%M:%S")

    return {
        "Name": {
            "title": [
                {
                    "text": {
                        "content": f"{data.symbol} #{data.ticket}"
                    }
                }
            ]
        },

        "Date": {
            "date": {
                "start": today
            }
        },

        "Open Time": {
            "rich_text": [
                {
                    "text": {
                        "content": open_time
                    }
                }
            ]
        },

        "Pair": {
            "rich_text": [
                {
                    "text": {
                        "content": data.symbol
                    }
                }
            ]
        },

        "Direction": {
            "select": {
                "name": data.direction or "Buy"
            }
        },

        "Status": {
            "select": {
                "name": "Open"
            }
        },

        "Entry Price": {
            "number": data.entry_price
        },

        "Stop Loss": {
            "number": data.stop_loss
        },

        "Lot Size": {
            "number": data.lot_size
        },

        "Ticket": {
            "number": data.ticket
        },
    }


def build_update_properties(data: TradePayload):

    properties = {}

    if data.stop_loss is not None:
        properties["Stop Loss"] = {
            "number": data.stop_loss
        }

    if data.lot_size is not None:
        properties["Lot Size"] = {
            "number": data.lot_size
        }

    if data.event == "close":

        properties["Status"] = {
            "select": {
                "name": "Closed"
            }
        }

        if data.exit_price is not None:
            properties["Exit Price"] = {
                "number": data.exit_price
            }

        if data.profit_loss is not None:
            properties["Profit / Loss"] = {
                "number": data.profit_loss
            }

        if data.result:
            properties["Result"] = {
                "select": {
                    "name": data.result
                }
            }

    return properties


def create_notion_trade(data: TradePayload):

    if not NOTION_DATABASE_ID:
        raise HTTPException(
            status_code=500,
            detail="NOTION_DATABASE_ID is missing"
        )

    url = "https://api.notion.com/v1/pages"

    payload = {
        "parent": {
            "database_id": NOTION_DATABASE_ID
        },
        "properties": build_create_properties(data)
    }

    response = requests.post(
        url,
        headers=notion_headers(),
        json=payload,
        timeout=15
    )

    if response.status_code not in [200, 201]:
        raise HTTPException(
            status_code=response.status_code,
            detail=response.text
        )

    return response.json()


def update_notion_trade(page_id: str, data: TradePayload):

    url = f"https://api.notion.com/v1/pages/{page_id}"

    payload = {
        "properties": build_update_properties(data)
    }

    response = requests.patch(
        url,
        headers=notion_headers(),
        json=payload,
        timeout=15
    )

    if response.status_code not in [200, 201]:
        raise HTTPException(
            status_code=response.status_code,
            detail=response.text
        )

    return response.json()


def send_line_message(text: str):

    headers = line_headers()

    if not headers or not LINE_USER_ID:
        return None

    url = "https://api.line.me/v2/bot/message/push"

    payload = {
        "to": LINE_USER_ID,
        "messages": [
            {
                "type": "text",
                "text": text
            }
        ]
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=15
    )

    return response.status_code


def build_line_text(data: TradePayload):

    if data.event == "open":

        return (
            "🟢 Open Trade\n"
            f"{data.symbol} {data.direction}\n"
            f"Entry: {data.entry_price}\n"
            f"SL: {data.stop_loss}\n"
            f"Lot: {data.lot_size}\n"
            f"Ticket: {data.ticket}"
        )

    if data.event == "close":

        return (
            "🔴 Closed Trade\n"
            f"{data.symbol}\n"
            f"Exit: {data.exit_price}\n"
            f"Result: {data.result}\n"
            f"Profit/Loss: {data.profit_loss}\n"
            f"Ticket: {data.ticket}"
        )

    return (
        "🔄 Trade Updated\n"
        f"{data.symbol}\n"
        f"SL: {data.stop_loss}\n"
        f"Lot: {data.lot_size}\n"
        f"Ticket: {data.ticket}"
    )


@app.get("/")
def health_check():

    return {
        "status": "ok",
    }


@app.post("/webhook/mt5")
def mt5_webhook(data: TradePayload):

    if data.event not in ["open", "update", "close"]:
        raise HTTPException(
            status_code=400,
            detail="event must be open, update, or close"
        )

    page_id = find_notion_page_by_ticket(data.ticket)

    if data.event == "open":

        if page_id:
            notion_result = update_notion_trade(page_id, data)
            action = "updated_existing"

        else:
            notion_result = create_notion_trade(data)
            action = "created"

    else:

        if not page_id:
            raise HTTPException(
                status_code=404,
                detail="Notion trade page not found by Ticket"
            )

        notion_result = update_notion_trade(page_id, data)
        action = "updated"

    line_status = send_line_message(build_line_text(data))

    return {
        "ok": True,
        "action": action,
        "event": data.event,
        "ticket": data.ticket,
        "line_status": line_status,
        "notion_page_id": notion_result.get("id")
    }


@app.post("/callback")
async def callback(request: Request):
    body = await request.json()
    print("LINE CALLBACK:", body, flush=True)
    return {"status": "ok"}