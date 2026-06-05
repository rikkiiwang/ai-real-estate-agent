ENV["RAILS_ENV"] ||= "test"
require_relative "../config/environment"
require "rails/test_help"
require_relative "support/fake_brain"

# The Concierge's embedded chatbot calls the brain over gRPC. In tests (and when
# seeds load in tests) use a deterministic offline fake by default, so no test
# makes a real network call. Individual tests can still override brain_factory.
ConciergeService.brain_factory = -> { FakeBrain.new }

module ActiveSupport
  class TestCase
    # Parallelism disabled: the hermetic sqlite test DB is a single file and the
    # append-only AuditEvent hash chain is global per-process, so serial runs
    # keep both deterministic.
    # parallelize(workers: :number_of_processors)

    # Setup all fixtures in test/fixtures/*.yml for all tests in alphabetical order.
    fixtures :all

    # Add more helper methods to be used by all tests here...
  end
end
