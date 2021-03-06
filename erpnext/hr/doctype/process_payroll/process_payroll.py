# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe
from frappe.utils import cint, flt, nowdate
from frappe import _
import collections
from collections import defaultdict

from frappe.model.document import Document

class ProcessPayroll(Document):

	def get_emp_list(self):
		"""
			Returns list of active employees based on selected criteria
			and for which salary structure exists
		"""
		cond = self.get_filter_condition()
		cond += self.get_joining_releiving_condition()

		sal_struct = frappe.db.sql("""
				select name from `tabSalary Structure`
				where docstatus != 2 and company = %(company)s and
				ifnull(salary_slip_based_on_timesheet,0) = %(salary_slip_based_on_timesheet)s""",
				{"company": self.company, "salary_slip_based_on_timesheet":self.salary_slip_based_on_timesheet})
		
		if sal_struct:
			cond += "and t2.parent IN %(sal_struct)s "

			emp_list = frappe.db.sql("""
				select t1.name
				from `tabEmployee` t1, `tabSalary Structure Employee` t2
				where t1.docstatus!=2 and t1.name = t2.employee
			%s """% cond, {"sal_struct": sal_struct})

			return emp_list


	def get_filter_condition(self):
		self.check_mandatory()

		cond = ''
		for f in ['company', 'branch', 'department', 'designation']:
			if self.get(f):
				cond += " and t1." + f + " = '" + self.get(f).replace("'", "\'") + "'"

		return cond


	def get_joining_releiving_condition(self):
		cond = """
			and ifnull(t1.date_of_joining, '0000-00-00') <= '%(from_date)s'
			and ifnull(t1.relieving_date, '2199-12-31') >= '%(to_date)s'
		""" % {"from_date": self.from_date, "to_date": self.to_date}
		return cond


	def check_mandatory(self):
		for f in ['company', 'from_date', 'to_date']:
			if not self.get(f):
				frappe.throw(_("Please set {0}").format(f))

	def create_sal_slip(self):
		"""
			Creates salary slip for selected employees if already not created
		"""
		self.check_permission('write')

		emp_list = self.get_emp_list()
		ss_list = []
		if emp_list:
			for emp in emp_list:
				if not frappe.db.sql("""select name from `tabSalary Slip`
						where docstatus!= 2 and employee = %s and start_date >= %s and end_date <= %s and company = %s
						""", (emp[0], self.from_date, self.to_date, self.company)):
					if self.salary_slip_based_on_timesheet:
						ss = frappe.get_doc({
							"doctype": "Salary Slip",
							"salary_slip_based_on_timesheet": self.salary_slip_based_on_timesheet,
							"start_date": self.from_date,
							"end_date": self.to_date,
							"employee": emp[0],
							"employee_name": frappe.get_value("Employee", {"name":emp[0]}, "employee_name"),
							"company": self.company,
							"posting_date": self.posting_date
						})
					else:
						ss = frappe.get_doc({
							"doctype": "Salary Slip",
							"salary_slip_based_on_timesheet": self.salary_slip_based_on_timesheet,
							"fiscal_year": self.fiscal_year,
							"month": self.month,
							"employee": emp[0],
							"employee_name": frappe.get_value("Employee", {"name":emp[0]}, "employee_name"),
							"company": self.company,
							"posting_date": self.posting_date
						})	
					ss.insert()
					ss_list.append(ss.name)
		return self.create_log(ss_list)


	def create_log(self, ss_list):
		log = "<p>" + _("No employee for the above selected criteria OR salary slip already created") + "</p>"
		if ss_list:
			log = "<b>" + _("Salary Slip Created") + "</b>\
			<br><br>%s" % '<br>'.join(self.format_as_links(ss_list))
		return log


	def get_sal_slip_list(self, ss_status, as_dict=False):
		"""
			Returns list of salary slips based on selected criteria
		"""
		cond = self.get_filter_condition()
			
		ss_list = frappe.db.sql("""
			select t1.name, t1.salary_structure from `tabSalary Slip` t1
			where t1.docstatus = %s and t1.start_date >= %s and t1.end_date <= %s 
			and (t1.journal_entry is null or t1.journal_entry = "") and ifnull(salary_slip_based_on_timesheet,0) = %s %s
		""" % ('%s', '%s', '%s','%s', cond), (ss_status, self.from_date, self.to_date, self.salary_slip_based_on_timesheet), as_dict=as_dict)
		return ss_list


	def submit_salary_slip(self):
		"""
			Submit all salary slips based on selected criteria
		"""
		self.check_permission('write')

		ss_list = self.get_sal_slip_list(ss_status=0)
		not_submitted_ss = []
		for ss in ss_list:
			ss_obj = frappe.get_doc("Salary Slip",ss[0])
			if ss_obj.net_pay<0:
				not_submitted_ss.append(ss[0])
			else:
				try:
					ss_obj.submit()
				except Exception,e:
					not_submitted_ss.append(ss[0])

		return self.create_submit_log(ss_list, not_submitted_ss)


	def create_submit_log(self, all_ss, not_submitted_ss):
		log = ''
		if not all_ss:
			log = "No salary slip found to submit for the above selected criteria"
		else:
			all_ss = [d[0] for d in all_ss]

		submitted_ss = self.format_as_links(list(set(all_ss) - set(not_submitted_ss)))
		if submitted_ss:
			log = """
				<b>Salary Slips Submitted:</b> <br><br>%s
				""" % ('<br>'.join(submitted_ss))

		if not_submitted_ss:
			log += """
				<b>Not Submitted Salary Slips: </b>\
				<br><br> %s <br><br> \
				Reason: <br>\
				May be net pay is less than 0 <br>
				May be company email id specified in employee master is not valid. <br> \
				Please mention correct email id in employee master or if you don't want to \
				send mail, uncheck 'Send Email' checkbox. <br>\
				Then try to submit Salary Slip again.
			"""% ('<br>'.join(not_submitted_ss))
		return log

	def format_as_links(self, ss_list):
		return ['<a href="#Form/Salary Slip/{0}">{0}</a>'.format(s) for s in ss_list]


	def get_total_salary(self):
		"""
			Get total salary amount from submitted salary slip based on selected criteria
		"""
		cond = self.get_filter_condition()
		tot = frappe.db.sql("""
			select sum(rounded_total) from `tabSalary Slip` t1
			where t1.docstatus = 1 and start_date >= %s and end_date <= %s %s
		""" % ('%s', '%s', cond), (self.from_date, self.to_date))

		return flt(tot[0][0])
		
	def get_salary_component_account(self, salary_component):
		account = frappe.db.get_value("Salary Component Account",
			{"parent": salary_component, "company": self.company}, "default_account")
	
		if not account:
			frappe.throw(_("Please set default account in Salary Component {0}")
				.format(salary_component))
	
		return account	
		
	def get_salary_components(self, component_type):
		salary_slips = self.get_sal_slip_list(ss_status = 1, as_dict = True)
		if salary_slips:
			salary_components = frappe.db.sql("""select salary_component, amount, parentfield
				from `tabSalary Detail` where parentfield = '%s' and parent in (%s)""" %
				(component_type, ', '.join(['%s']*len(salary_slips))), tuple([d.name for d in salary_slips]), as_dict=True)				
			return salary_components
		
	def get_salary_component_total(self, component_type = None):
		salary_components = self.get_salary_components(component_type)
		if salary_components:
			component_dict = {}
			for item in salary_components:			
				component_dict[item['salary_component']] = component_dict.get(item['salary_component'], 0) + item['amount']
			account_details = self.get_account(component_dict = component_dict)
			return account_details
			
	def get_account(self, component_dict = None):
		account_dict = {}
		for s, a in component_dict.items():
			account = self.get_salary_component_account(s)
			account_dict[account] = account_dict.get(account, 0) + a		
		return account_dict
		
	
	def make_journal_entry(self, reference_number = None, reference_date = None):
		self.check_permission('write')
		earnings = self.get_salary_component_total(component_type = "earnings") or {}
		deductions = self.get_salary_component_total(component_type = "deductions") or {}
		jv_name = ""

		if earnings or deductions:
			journal_entry = frappe.new_doc('Journal Entry')
			journal_entry.voucher_type = 'Bank Entry'
			journal_entry.user_remark = _('Payment of salary from {0} to {1}').format(self.from_date,
				self.to_date)
			journal_entry.company = self.company
			journal_entry.posting_date = nowdate()
		
			account_amt_list = []
			adjustment_amt = 0
			for acc, amt in earnings.items():
				adjustment_amt = adjustment_amt+amt
				account_amt_list.append({
						"account": acc,
						"debit_in_account_currency": amt
					})
			for acc, amt in deductions.items():
				adjustment_amt = adjustment_amt-amt
				account_amt_list.append({
						"account": acc,
						"credit_in_account_currency": amt
					})
			account_amt_list.append({
					"account": self.payment_account,
					"credit_in_account_currency": adjustment_amt
				})		
			journal_entry.set("accounts", account_amt_list)
			journal_entry.cheque_no = reference_number
			journal_entry.cheque_date = reference_date
			journal_entry.save()
			try:
				journal_entry.submit()
				jv_name = journal_entry.name
				self.update_salary_slip_status(jv_name = jv_name)
			except Exception, e:
				frappe.msgprint(e)
		return self.create_jv_log(jv_name)
	

	def create_jv_log(self, jv_name):
		log = "<p>" + _("No submitted Salary Slip found") + "</p>"
		if jv_name:
			log = "<b>" + _("Journal Entry Submitted") + "</b>\
				%s" % '<br>''<a href="#Form/Journal Entry/{0}">{0}</a>'.format(jv_name)
		return log	
	
	def update_salary_slip_status(self, jv_name = None):
		ss_list = self.get_sal_slip_list(ss_status=1)
		for ss in ss_list:
			ss_obj = frappe.get_doc("Salary Slip",ss[0])
			frappe.db.set_value("Salary Slip", ss_obj.name, "status", "Paid")
			frappe.db.set_value("Salary Slip", ss_obj.name, "journal_entry", jv_name)


@frappe.whitelist()
def get_month_details(year, month):
	ysd = frappe.db.get_value("Fiscal Year", year, "year_start_date")
	if ysd:
		from dateutil.relativedelta import relativedelta
		import calendar, datetime
		diff_mnt = cint(month)-cint(ysd.month)
		if diff_mnt<0:
			diff_mnt = 12-int(ysd.month)+cint(month)
		msd = ysd + relativedelta(months=diff_mnt) # month start date
		month_days = cint(calendar.monthrange(cint(msd.year) ,cint(month))[1]) # days in month
		med = datetime.date(msd.year, cint(month), month_days) # month end date
		return frappe._dict({
			'year': msd.year,
			'month_start_date': msd,
			'month_end_date': med,
			'month_days': month_days
		})
	else:
		frappe.throw(_("Fiscal Year {0} not found").format(year))