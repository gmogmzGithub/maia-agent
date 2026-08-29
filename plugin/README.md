# Hermes Plugin

This directory contains the standalone Maia plugin loaded by Hermes.

The plugin exposes typed operations to Hermes and calls Maia Product APIs. It
must stay thin: no Product database imports, no direct Calendar or WhatsApp
credentials, and no business-rule ownership. If a tool needs new authority, add
that authority to the Product domain first and expose it through an authenticated
Product route.
