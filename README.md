# MCP Server for Kontomanager

An unofficial [MCP](https://modelcontextprotocol.io) server for the Austrian mobile brands **yesss!**, **Georg**, and **XOXO**.

This server acts as a bridge, exposing the functionalities of the Kontomanager web interface through a structured set of MCP tools. It allows you to programmatically read account information, check usage, download bills, and modify settings like call forwardings.

## ✨ Features

This server is designed with a **tool-first** approach for broad client support. It provides a comprehensive set of functions mirroring the web portal:

*   **Read Account Data**: Fetch usage, credit, plan details, phone numbers, and call history.
*   **Manage Bills**: List past bills and download their PDF content.
*   **Modify Settings**: Change SIM settings like roaming and configure detailed call forwarding rules.
*   **High-Level Workflows**: Use simple tools for common actions like disabling voicemail.

## 🛠️ Available Tools

The server exposes all functionality through tools, which can be called by an MCP client or an LLM.

### Data Retrieval Tools
*   `get_account_usage()`: Retrieves the main account overview, including plan details, usage statistics, and credit balance.
*   `get_phone_numbers()`: Lists all phone numbers associated with the logged-in account.
*   `list_bills()`: Fetches a list of available bills (metadata only).
*   `download_bill(bill_number, document_type)`: Fetches a specific bill or its itemized record (EGN) and returns its binary content (PDF).
*   `get_call_history()`: Retrieves a list of recent calls and SMS messages.
*   `get_sim_settings()`: Reads the current state of all SIM-related settings (e.g., roaming status, data barring).
*   `get_call_forwarding_settings()`: Reads the current call forwarding and voicemail settings.

### Action & Workflow Tools
*   `switch_active_phone_number(subscriber_id)`: Switches the active phone number for the session.
*   `toggle_roaming(enabled)`: A simple tool to enable or disable international roaming.
*   `set_sim_setting(setting_name, enabled)`: A low-level tool to enable or disable a specific SIM setting.
*   `set_call_forwarding_rule(...)`: A low-level tool to configure a specific call forwarding rule (e.g., forward when busy to a specific number).

## 🗣️ Example Usage

You can interact with this server using natural language in a compatible MCP client. The client's LLM will select and execute the appropriate tools.

*   **"What's my current data usage and credit?"**
    *   → Calls `get_account_usage()`
*   **"Show me my last few bills."**
    *   → Calls `list_bills()`
*   **"Download my bill number 8177 and the itemized record for it."**
    *   → Calls `download_bill(bill_number='8177', document_type='bill')`
    *   → Calls `download_bill(bill_number='8177', document_type='egn')`
*   **"Turn on roaming for my trip."**
    *   → Calls `toggle_roaming(enabled=True)`
*   **"Forward all my calls to +436811234567 when my line is busy."**
    *   → Calls `set_call_forwarding_rule(condition='wtel', target='a', target_number='+436811234567')`

## ⚙️ Configuration

The server requires your Kontomanager credentials. These must be provided via environment variables, which you will set in your MCP client's configuration file.

The required variables are:
*   `KONTOMANAGER_BRAND`: The brand of your mobile carrier. Supported values: `"yesss"`, `"georg"`, `"xoxo"`.
*   `KONTOMANAGER_USERNAME`: Your login phone number or username.
*   `KONTOMANAGER_PASSWORD`: Your Kontomanager account password.

## 🚀 Setup and Usage

This project is an MCP server and is designed to be launched and managed by an MCP client. You do not run it standalone.

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/dhofer/mcp-server-kontomanager.git
    ```

2.  **Configure your MCP client:**
    Add a new server definition to your MCP client's configuration file. The command will use `uv run` to execute the server from its local directory. Make sure to use the **absolute path** to the cloned repository.

    ```json
    {
      "mcpServers": {
        "kontomanager": {
          "command": "uv",
          "args": [
            "run",
            "--directory",
            "/absolute/path/to/mcp-server-kontomanager",
            "python",
            "src/server.py"
          ],
          "env": {
            "KONTOMANAGER_BRAND": "yesss",
            "KONTOMANAGER_USERNAME": "43681...",
            "KONTOMANAGER_PASSWORD": "your_secret_password"
          }
        }
      }
    }
    ```

---

## ⚠️ Important Warnings: Read Before Use

### **Data Privacy**
When you use this MCP server, any data retrieved by the tools (like your account usage, phone numbers, or bill details) is sent to the Large Language Model (LLM) that powers your MCP client. **This means a third-party company (e.g., OpenAI, Google, Anthropic) will process this potentially sensitive information.** Please be aware of the privacy implications and review your LLM provider's policies before using this server.

### **Financial Risk**
This server provides tools that can change your mobile account settings in real-time. Actions like `toggle_roaming` or `set_call_forwarding_rule` can lead to **significant, real-world charges on your phone bill**, especially if misconfigured. You are solely responsible for any and all costs incurred as a result of using these tools. **Use them with extreme caution.**

### 🧑‍💻 Development Philosophy

This project is, for all intents and purposes, **vibe coded**. It was built based on intuition and the specific needs of the developer. While it aims to be functional, it may not follow the strictest engineering practices and has limited tests. Pull requests for improving robustness, adding tests, or refining the code are highly encouraged!

***Disclaimer:** This is an unofficial project and is not affiliated with, endorsed, or supported by A1 Telekom Austria AG or any of its brands. The Kontomanager website structure can change at any time, which may break the functionality of this server. Use at your own risk.*
