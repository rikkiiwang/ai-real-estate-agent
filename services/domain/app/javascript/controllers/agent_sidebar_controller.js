import { Controller } from "@hotwired/stimulus"

// Drives the persistent agent sidebar:
//  - syncs the current page context (a listing address) into hidden fields on
//    every Turbo visit, so a question is automatically about the home you're on
//  - shows a "thinking" indicator while the orchestrator runs
//  - Enter sends, Shift+Enter makes a newline
//  - keeps the conversation scrolled to the latest message
export default class extends Controller {
  static targets = ["messages", "input", "thinking", "address", "listingId", "form"]

  connect() {
    this.syncContext = this.syncContext.bind(this)
    document.addEventListener("turbo:load", this.syncContext)
    this.syncContext()
    this.scrollToBottom()
  }

  disconnect() {
    document.removeEventListener("turbo:load", this.syncContext)
  }

  // Read <div id="agent-context" data-address data-listing-id> from the current
  // page and copy it into the form so the agent knows what we're looking at.
  syncContext() {
    const ctx = document.getElementById("agent-context")
    const address = ctx?.dataset.address || ""
    const listingId = ctx?.dataset.listingId || ""
    if (this.hasAddressTarget) this.addressTarget.value = address
    if (this.hasListingIdTarget) this.listingIdTarget.value = listingId
  }

  enter(event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault()
      if (this.inputTarget.value.trim()) this.formTarget.requestSubmit()
    }
  }

  start() {
    if (this.hasThinkingTarget) this.thinkingTarget.hidden = false
    this.scrollToBottom()
  }

  end() {
    if (this.hasThinkingTarget) this.thinkingTarget.hidden = true
    this.inputTarget.value = ""
    this.scrollToBottom()
  }

  scrollToBottom() {
    requestAnimationFrame(() => {
      if (this.hasMessagesTarget) this.messagesTarget.scrollTop = this.messagesTarget.scrollHeight
    })
  }
}
