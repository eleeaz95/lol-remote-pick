# Security Policy 🔒

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

---

## Technical & Riot Integrity Architecture

**LoL Remote Pick** is designed with security and compliance as primary architectural constraints:

1. **Localhost-Only LCU Access**: The application communicates exclusively with the local League of Legends client on `127.0.0.1` using standard HTTP Basic Authentication tokens generated dynamically by the Riot Client process.
2. **Zero Memory Tampering**: This application does not read/write game memory, inject DLLs, or interact with Riot Vanguard.
3. **LAN Scope**: The mobile hub binds by default to your local network interface for authorized devices on the same Wi-Fi.

---

## Reporting a Vulnerability

If you discover a security vulnerability or exploit within LoL Remote Pick:

1. **Do not** open a public GitHub issue.
2. Please send a private email with details, proof of concept, and reproduction steps to:  
   📧 **`eleeaz.lp@gmail.com`** (or open a private security advisory via GitHub Security Advisories).
3. We will acknowledge receipt within 48 hours and work on a coordinated fix and advisory.

Thank you for helping keep the community safe!
