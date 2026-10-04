// Report views of place analyses, by process id (project workspace). A process without one shows its JSON.
import type { Component } from 'svelte';
import type { AnalysisRun } from '../api';
import AgPotentialReport from './AgPotentialReport.svelte';
import FireRiskReport from './FireRiskReport.svelte';
import './report.css';

export const REPORTS: Record<string, Component<{ run: AnalysisRun }>> = {
	'py.agricultural_potential': AgPotentialReport,
	'py.fire_risk': FireRiskReport
};
