import { Controller } from "@hotwired/stimulus"

// Drives the persistent agent sidebar:
//  - syncs the current page context (a listing address) into hidden fields on
//    every Turbo visit, so a question is automatically about the home you're on
//  - shows a "thinking" indicator while the orchestrator runs
//  - Enter sends, Shift+Enter makes a newline
//  - keeps the conversation scrolled to the latest message
export default class extends Controller {
  static targets = ["messages", "input", "thinking", "address", "listingId", "form", "mic", "channel"]

  connect() {
    this.syncContext = this.syncContext.bind(this)
    document.addEventListener("turbo:load", this.syncContext)
    this.syncContext()
    this.scrollToBottom()
    this.setupSpeech()
  }

  disconnect() {
    document.removeEventListener("turbo:load", this.syncContext)
    if (this.recognition) this.recognition.abort()
  }

  // Voice input: if the browser supports the Web Speech API, reveal the mic so a
  // visitor can SPEAK to Atlas instead of typing (transcribes into the box).
  setupSpeech() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR || !this.hasMicTarget) return
    this.recognition = new SR()
    this.recognition.lang = "en-US"
    this.recognition.interimResults = false
    this.recognition.onresult = (e) => {
      const text = Array.from(e.results).map((r) => r[0].transcript).join(" ")
      this.inputTarget.value = (this.inputTarget.value + " " + text).trim()
      this.inputTarget.focus()
    }
    this.recognition.onend = () => { this.listening = false; this.micTarget.classList.remove("is-live") }
    this.micTarget.hidden = false
    // When a visitor speaks, treat the turn as the Voice channel.
    if (this.hasChannelTarget) this.voiceOnDictate = true
  }

  dictate() {
    if (!this.recognition) return
    if (this.listening) { this.recognition.stop(); return }
    if (this.hasChannelTarget) this.channelTarget.value = "voice"
    this.listening = true
    this.micTarget.classList.add("is-live")
    try { this.recognition.start() } catch (_) { this.listening = false }
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
