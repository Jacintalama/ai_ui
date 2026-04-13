"""
Create and format a Google Sheets spreadsheet for meeting transcripts.

This script creates a professionally formatted sheet with:
- Header row (bold, white text, dark blue background)
- Frozen header row
- Alternating row colors
- Conditional formatting on Status column
- Auto-filter, text wrapping, and proper column widths

Usage:
    pip install google-auth google-auth-oauthlib google-api-python-client
    python create-meeting-sheet.py

Environment variables:
    GOOGLE_CLIENT_ID      - OAuth client ID
    GOOGLE_CLIENT_SECRET  - OAuth client secret

On first run, opens a browser for OAuth consent. Stores token in token.json.
Prints the spreadsheet ID and URL when done.
"""

import os
import json
import sys
from pathlib import Path

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
except ImportError:
    print("Missing dependencies. Install with:")
    print("  pip install google-auth google-auth-oauthlib google-api-python-client")
    sys.exit(1)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

SHEET_TITLE = "Meeting Transcripts"
SPREADSHEET_TITLE = "Fathom Meeting Transcripts"

# Column definitions: (header, pixel width)
COLUMNS = [
    ("Date", 120),
    ("Meeting Title", 250),
    ("Attendees", 200),
    ("AI Summary", 400),
    ("Action Items", 350),
    ("Fathom Link", 200),
    ("Status", 100),
]

# Colors (RGB 0-1 float)
DARK_BLUE = {"red": 0.102, "green": 0.451, "blue": 0.910}  # #1a73e8
WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}
LIGHT_BLUE = {"red": 0.910, "green": 0.941, "blue": 0.996}  # #e8f0fe
GREEN_BG = {"red": 0.851, "green": 0.918, "blue": 0.827}  # #d9ebd3
YELLOW_BG = {"red": 1.0, "green": 0.949, "blue": 0.800}  # #fff2cc


def get_credentials() -> Credentials:
    """Authenticate via OAuth using env vars or existing token."""
    token_path = Path(__file__).parent / "token.json"
    creds = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            client_id = os.environ.get("GOOGLE_CLIENT_ID")
            client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")

            if not client_id or not client_secret:
                print("Error: Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET env vars.")
                sys.exit(1)

            client_config = {
                "installed": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"],
                }
            }

            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_path, "w") as f:
            f.write(creds.to_json())
        print(f"Token saved to {token_path}")

    return creds


def create_spreadsheet(service) -> str:
    """Create a new spreadsheet and return its ID."""
    body = {
        "properties": {"title": SPREADSHEET_TITLE},
        "sheets": [
            {
                "properties": {
                    "title": SHEET_TITLE,
                    "gridProperties": {
                        "rowCount": 1000,
                        "columnCount": len(COLUMNS),
                        "frozenRowCount": 1,
                    },
                }
            }
        ],
    }

    spreadsheet = service.spreadsheets().create(body=body).execute()
    return spreadsheet["spreadsheetId"]


def format_spreadsheet(service, spreadsheet_id: str) -> None:
    """Apply all formatting to the spreadsheet."""
    sheet_id = 0  # First sheet

    requests = []

    # --- Write header row ---
    header_values = [col[0] for col in COLUMNS]
    requests.append(
        {
            "updateCells": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": len(COLUMNS),
                },
                "rows": [
                    {
                        "values": [
                            {
                                "userEnteredValue": {"stringValue": header},
                                "userEnteredFormat": {
                                    "textFormat": {
                                        "bold": True,
                                        "fontSize": 11,
                                        "foregroundColorStyle": {
                                            "rgbColor": WHITE
                                        },
                                    },
                                    "backgroundColor": DARK_BLUE,
                                    "horizontalAlignment": "CENTER",
                                    "verticalAlignment": "MIDDLE",
                                    "padding": {
                                        "top": 4,
                                        "bottom": 4,
                                        "left": 6,
                                        "right": 6,
                                    },
                                },
                            }
                            for header in header_values
                        ]
                    }
                ],
                "fields": "userEnteredValue,userEnteredFormat",
            }
        }
    )

    # --- Set column widths ---
    for i, (_, width) in enumerate(COLUMNS):
        requests.append(
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": i,
                        "endIndex": i + 1,
                    },
                    "properties": {"pixelSize": width},
                    "fields": "pixelSize",
                }
            }
        )

    # --- Set header row height ---
    requests.append(
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": 0,
                    "endIndex": 1,
                },
                "properties": {"pixelSize": 36},
                "fields": "pixelSize",
            }
        }
    )

    # --- Alternating row colors (banding) ---
    requests.append(
        {
            "addBanding": {
                "bandedRange": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": 1000,
                        "startColumnIndex": 0,
                        "endColumnIndex": len(COLUMNS),
                    },
                    "rowProperties": {
                        "headerColor": DARK_BLUE,
                        "firstBandColor": WHITE,
                        "secondBandColor": LIGHT_BLUE,
                    },
                }
            }
        }
    )

    # --- Text wrap on AI Summary (col D, index 3) and Action Items (col E, index 4) ---
    for col_index in [3, 4]:
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "endRowIndex": 1000,
                        "startColumnIndex": col_index,
                        "endColumnIndex": col_index + 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "wrapStrategy": "WRAP",
                            "verticalAlignment": "TOP",
                        }
                    },
                    "fields": "userEnteredFormat(wrapStrategy,verticalAlignment)",
                }
            }
        )

    # --- Date format on column A (index 0) ---
    requests.append(
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1,
                    "endRowIndex": 1000,
                    "startColumnIndex": 0,
                    "endColumnIndex": 1,
                },
                "cell": {
                    "userEnteredFormat": {
                        "numberFormat": {
                            "type": "DATE",
                            "pattern": "yyyy-mm-dd",
                        }
                    }
                },
                "fields": "userEnteredFormat.numberFormat",
            }
        }
    )

    # --- Auto-filter on all columns ---
    requests.append(
        {
            "setBasicFilter": {
                "filter": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": 1000,
                        "startColumnIndex": 0,
                        "endColumnIndex": len(COLUMNS),
                    }
                }
            }
        }
    )

    # --- Conditional formatting: Status = "Processed" -> green ---
    requests.append(
        {
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [
                        {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,
                            "endRowIndex": 1000,
                            "startColumnIndex": 6,
                            "endColumnIndex": 7,
                        }
                    ],
                    "booleanRule": {
                        "condition": {
                            "type": "TEXT_EQ",
                            "values": [{"userEnteredValue": "Processed"}],
                        },
                        "format": {"backgroundColor": GREEN_BG},
                    },
                },
                "index": 0,
            }
        }
    )

    # --- Conditional formatting: Status = "Processing..." -> yellow ---
    requests.append(
        {
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [
                        {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,
                            "endRowIndex": 1000,
                            "startColumnIndex": 6,
                            "endColumnIndex": 7,
                        }
                    ],
                    "booleanRule": {
                        "condition": {
                            "type": "TEXT_EQ",
                            "values": [{"userEnteredValue": "Processing..."}],
                        },
                        "format": {"backgroundColor": YELLOW_BG},
                    },
                },
                "index": 1,
            }
        }
    )

    # Execute all formatting requests in one batch
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body={"requests": requests}
    ).execute()


def main() -> None:
    print("Authenticating with Google...")
    creds = get_credentials()
    service = build("sheets", "v4", credentials=creds)

    print(f"Creating spreadsheet: {SPREADSHEET_TITLE}")
    spreadsheet_id = create_spreadsheet(service)

    print("Applying formatting...")
    format_spreadsheet(service, spreadsheet_id)

    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
    print()
    print("=" * 60)
    print("Spreadsheet created successfully!")
    print(f"  ID:  {spreadsheet_id}")
    print(f"  URL: {url}")
    print()
    print("Next steps:")
    print(f"  1. Update n8n workflow CONFIGURE_SHEET_ID with: {spreadsheet_id}")
    print("  2. Share the sheet with your team or service account")
    print("  3. Configure Discord webhook URL in the n8n workflow")
    print("=" * 60)


if __name__ == "__main__":
    main()
