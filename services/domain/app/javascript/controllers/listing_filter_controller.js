import { Controller } from "@hotwired/stimulus"

// Auto-submits the listing filter form when a select changes, so region/beds
// filters apply without clicking Search. Price inputs still submit on Enter or
// the Search button. The form targets the "catalog" Turbo frame, so only the
// results update — the page does not reload.
export default class extends Controller {
  submit() {
    this.element.requestSubmit()
  }
}
