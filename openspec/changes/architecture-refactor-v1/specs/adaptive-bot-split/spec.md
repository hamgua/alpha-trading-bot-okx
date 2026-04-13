## ADDED Requirements

### Requirement: AdaptiveTradingBot shall delegate responsibilities to specialized Manager classes

The system SHALL split the AdaptiveTradingBot class into multiple specialized Manager classes to improve maintainability and testability.

#### Scenario: MarketRegimeManager handles market state detection
- **WHEN** AdaptiveTradingBot initializes
- **THEN** it SHALL create a MarketRegimeManager instance that manages MarketRegimeDetector, PerformanceTracker, and market state publishing

#### Scenario: StrategyExecutionManager handles strategy selection
- **WHEN** a trading cycle begins
- **THEN** StrategyExecutionManager SHALL select and execute the appropriate strategy based on current market state

#### Scenario: RiskControlManager handles risk evaluation
- **WHEN** before any trade execution
- **THEN** RiskControlManager SHALL evaluate risk parameters and provide risk-adjusted recommendations

#### Scenario: ParameterManager handles parameter updates
- **WHEN** ML learning produces new parameters
- **THEN** ParameterManager SHALL validate and apply parameter updates through ConfigUpdater interface

#### Scenario: LearningManager handles ML integration
- **WHEN** trading cycle completes
- **THEN** LearningManager SHALL collect performance data and trigger ML weight optimization

### Requirement: Manager classes shall communicate through defined interfaces

Each Manager class SHALL expose a clean interface for interaction with other components.

#### Scenario: Synchronous query
- **WHEN** other components need current state
- **THEN** Manager SHALL provide synchronous query methods

#### Scenario: Async operations
- **WHEN** operations require I/O or computation time
- **THEN** Manager SHALL expose async methods with proper error handling

### Requirement: AdaptiveTradingBot shall act as a facade coordinator

AdaptiveTradingBot SHALL coordinate multiple Managers without containing business logic itself.

#### Scenario: Trading cycle execution
- **WHEN** trading cycle triggers
- **THEN** AdaptiveTradingBot SHALL delegate to MarketRegimeManager → StrategyExecutionManager → RiskControlManager in sequence

#### Scenario: Error handling
- **WHEN** any Manager raises an exception
- **THEN** AdaptiveTradingBot SHALL catch and log the error, then decide whether to continue or halt
